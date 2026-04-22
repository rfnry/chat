from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import socketio
from pydantic import ValidationError
from rfnry_chat_protocol import (
    Identity,
    MessageEvent,
    RunError,
    StreamDeltaFrame,
    StreamEndFrame,
    StreamStartFrame,
    matches,
    parse_content_part,
    parse_event,
)

from rfnry_chat_server.broadcast.socketio import _tenant_room
from rfnry_chat_server.recipients import RecipientNotMemberError
from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.namespace import NamespaceViolation, parse_namespace_path
from rfnry_chat_server.store.types import EventCursor

if TYPE_CHECKING:
    from rfnry_chat_server.server.chat_server import ChatServer


DEFAULT_REPLAY_CAP = 500

_SERVER_LIFECYCLE_TYPES = frozenset(
    {
        "thread.created",
        "thread.member_added",
        "thread.member_removed",
        "thread.tenant_changed",
        "run.started",
        "run.completed",
        "run.failed",
        "run.cancelled",
    }
)


def thread_room(thread_id: str) -> str:
    return f"thread:{thread_id}"


# ---------------------------------------------------------------------------
# Task C1 finding (python-socketio 5.16.1)
# ---------------------------------------------------------------------------
# `socketio.AsyncServer._get_namespace_handler(namespace, args)` prepends the
# concrete namespace as the first positional arg when the handler was
# registered under the wildcard `"*"` — i.e. for a wildcard registration the
# namespace instance receives `trigger_event(event, namespace, *original_args)`
# instead of the usual `trigger_event(event, *original_args)`.
#
# For a static registration (e.g. `/`), no extra arg is injected, so the
# standard `trigger_event(event, *original_args)` contract holds.
#
# `ThreadNamespace.trigger_event` below therefore:
#   1) Detects wildcard mode via `self.namespace == "*"` and pops the extra
#      leading argument, stashing the concrete namespace on a per-sid dict so
#      that handlers can look it up via `self._concrete_namespace_for(sid)`.
#   2) Translates colon-separated socket.io event names (e.g. "thread:join")
#      into Python-safe method names (`on_thread_join`), because class-based
#      namespaces default to mapping `"thread_join"` (underscore) → method.
# ---------------------------------------------------------------------------


class ThreadNamespace(socketio.AsyncNamespace):
    def __init__(
        self,
        namespace: str,
        *,
        server: ChatServer,
        replay_cap: int,
    ) -> None:
        super().__init__(namespace)
        self._server = server
        self._replay_cap = replay_cap
        # Maps sid -> concrete namespace path; populated in trigger_event when
        # the namespace was registered with the "*" wildcard.
        self._sid_namespaces: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    async def trigger_event(self, event: str, *args: Any) -> Any:
        # When registered under "*", python-socketio prepends the concrete
        # namespace as args[0]. Pop it and cache by sid so handlers can look
        # it up later via _concrete_namespace_for.
        if self.namespace == "*" and args:
            concrete_ns = args[0]
            rest = args[1:]
            # sid is the handler's first positional arg for every event
            # we care about (connect/disconnect/thread:*, message:*, ...).
            if rest and isinstance(rest[0], str):
                sid = rest[0]
                self._sid_namespaces[sid] = concrete_ns
            args = rest

        method_name = "on_" + event.replace(":", "_").replace("-", "_")
        handler = getattr(self, method_name, None)
        if handler is None:
            return None
        try:
            result = handler(*args)
        except TypeError:
            # python-socketio 5.12+ passes a `reason` arg to disconnect;
            # older handlers only accept sid. Mimic the upstream fallback.
            if event == "disconnect" and args:
                result = handler(*args[:-1])
            else:
                raise
        if hasattr(result, "__await__"):
            result = await result

        # Clean up cached namespace mapping on disconnect.
        if event == "disconnect" and args and isinstance(args[0], str):
            self._sid_namespaces.pop(args[0], None)
        return result

    def _concrete_namespace_for(self, sid: str) -> str:
        """Return the concrete namespace the given sid connected to.

        When the namespace is registered statically (e.g. "/"), there is no
        ambiguity: `self.namespace` is the answer. Under wildcard mode we
        read the mapping populated in `trigger_event`; if the sid is missing
        from that mapping we raise explicitly rather than silently falling
        back to "/" (which isn't a registered namespace under wildcard mode
        and would produce confusing downstream errors).
        """
        if self.namespace != "*":
            return self.namespace
        ns = self._sid_namespaces.get(sid)
        if ns is None:
            raise RuntimeError(
                f"no concrete namespace cached for sid={sid!r}; trigger_event should have stashed it before dispatch"
            )
        return ns

    # ------------------------------------------------------------------
    # Session helpers — route to the concrete namespace under wildcard.
    # AsyncNamespace.{save_,get_}session normally default the namespace to
    # `self.namespace`, which is literally "*" in wildcard mode. The sid is
    # registered under the concrete path, so we must override.
    # ------------------------------------------------------------------
    async def save_session(self, sid: str, session: dict[str, Any], namespace: str | None = None) -> None:
        ns = namespace or self._concrete_namespace_for(sid)
        await self.server.save_session(sid, session, namespace=ns)

    async def get_session(self, sid: str, namespace: str | None = None) -> dict[str, Any]:
        ns = namespace or self._concrete_namespace_for(sid)
        return await self.server.get_session(sid, namespace=ns)

    async def enter_room(self, sid: str, room: str, namespace: str | None = None) -> None:
        ns = namespace or self._concrete_namespace_for(sid)
        await self.server.enter_room(sid, room, namespace=ns)

    async def leave_room(self, sid: str, room: str, namespace: str | None = None) -> None:
        ns = namespace or self._concrete_namespace_for(sid)
        await self.server.leave_room(sid, room, namespace=ns)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    async def on_connect(self, sid: str, environ: dict[str, Any], auth: Any = None) -> None:
        # `trigger_event` already stashed `sid -> concrete_ns` in
        # `_sid_namespaces` before dispatching us (wildcard mode only). If
        # we raise ConnectionRefusedError anywhere below, python-socketio
        # never dispatches `disconnect` for this sid, so we must clean up
        # the cache entry ourselves or it leaks forever on refused auth.
        try:
            handshake = _build_handshake(environ, auth)
            identity = await self._server.authenticate(handshake)
            if identity is None:
                raise socketio.exceptions.ConnectionRefusedError("unauthenticated")

            ns_keys = self._server.namespace_keys
            identity_tenant = _identity_tenant(identity)
            if ns_keys is not None:
                concrete_ns = self._concrete_namespace_for(sid)
                try:
                    ns_tenant = parse_namespace_path(concrete_ns, namespace_keys=ns_keys)
                except NamespaceViolation as exc:
                    raise socketio.exceptions.ConnectionRefusedError(f"namespace_invalid: {exc}") from exc

                for key, expected in ns_tenant.items():
                    if identity_tenant.get(key) != expected:
                        raise socketio.exceptions.ConnectionRefusedError(
                            f"namespace_mismatch: identity missing or mismatched key {key!r}"
                        )
                await self.save_session(
                    sid,
                    {
                        "identity": identity,
                        "namespace": concrete_ns,
                        "namespace_tenant": ns_tenant,
                    },
                )
            else:
                await self.save_session(sid, {"identity": identity})
            await self.enter_room(sid, f"inbox:{identity.id}")
            try:
                tenant_room_name = _tenant_room(identity_tenant, namespace_keys=ns_keys)
            except NamespaceViolation as exc:
                raise socketio.exceptions.ConnectionRefusedError(f"namespace_invalid: tenant room: {exc}") from exc
            await self.enter_room(sid, tenant_room_name)
        except socketio.exceptions.ConnectionRefusedError:
            self._sid_namespaces.pop(sid, None)
            raise

    async def _check_namespace_match(self, sid: str, thread_tenant: dict[str, str]) -> bool:
        """Return True if the thread's tenant agrees with the session's
        namespace_tenant on every namespace_keys entry. Callers should treat
        a False return as `not_found` (do not leak existence)."""
        if self._server.namespace_keys is None:
            return True
        session = await self.get_session(sid)
        ns_tenant: dict[str, str] = session.get("namespace_tenant", {})
        for key, expected in ns_tenant.items():
            if thread_tenant.get(key) != expected:
                return False
        return True

    async def on_thread_join(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        identity = await _identity(self, sid)
        thread_id = data.get("thread_id")
        if not isinstance(thread_id, str):
            return _error("invalid_request", "thread_id required")

        thread = await self._server.store.get_thread(thread_id)
        if thread is None or not matches(thread.tenant, _identity_tenant(identity)):
            return _error("not_found", "thread not found")
        if not await self._check_namespace_match(sid, thread.tenant):
            return _error("not_found", "thread not found")
        if not await self._server.check_authorize(identity, thread_id, "thread.read"):
            return _error("forbidden", "not authorized: thread.read")

        await self.enter_room(sid, thread_room(thread_id))

        replayed: list[dict[str, Any]] = []
        replay_truncated = False
        since = data.get("since")
        if isinstance(since, dict):
            cursor = EventCursor(
                created_at=datetime.fromisoformat(since["created_at"]),
                id=since["id"],
            )
            page = await self._server.store.list_events(thread_id, since=cursor, limit=self._replay_cap + 1)
            items = page.items
            if len(items) > self._replay_cap:
                replay_truncated = True
                items = items[: self._replay_cap]
            replayed = [e.model_dump(mode="json", by_alias=True) for e in items]

        return {
            "thread_id": thread_id,
            "replayed": replayed,
            "replay_truncated": replay_truncated,
        }

    async def on_thread_leave(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        thread_id = data.get("thread_id")
        if not isinstance(thread_id, str):
            return _error("invalid_request", "thread_id required")
        # Deliberately no _check_namespace_match here: leave_room is scoped to
        # the sid's concrete namespace via the overridden `leave_room`, and
        # leaving a room you were never in is a Socket.IO no-op. Enforcing the
        # check would add work without changing behavior.
        await self.leave_room(sid, thread_room(thread_id))
        return {"thread_id": thread_id, "left": True}

    async def on_message_send(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        identity = await _identity(self, sid)
        thread_id = data.get("thread_id")
        draft = data.get("draft")
        if not isinstance(thread_id, str) or not isinstance(draft, dict):
            return _error("invalid_request", "thread_id and draft required")

        thread = await self._server.store.get_thread(thread_id)
        if thread is None or not matches(thread.tenant, _identity_tenant(identity)):
            return _error("not_found", "thread not found")
        if not await self._check_namespace_match(sid, thread.tenant):
            return _error("not_found", "thread not found")
        if not await self._server.check_authorize(identity, thread_id, "message.send"):
            return _error("forbidden", "not authorized: message.send")

        raw_content = draft.get("content") or []
        if not raw_content:
            return _error("invalid_request", "message draft must include content")
        parts = [parse_content_part(p) for p in raw_content]

        raw_recipients = draft.get("recipients")
        if raw_recipients is not None and not isinstance(raw_recipients, list):
            return _error("invalid_request", "recipients must be a list of identity ids")

        event = MessageEvent(
            id=f"evt_{secrets.token_hex(8)}",
            thread_id=thread_id,
            author=identity,
            created_at=datetime.now(UTC),
            metadata=draft.get("metadata") or {},
            client_id=draft.get("client_id"),
            recipients=raw_recipients,
            content=parts,
        )
        try:
            appended = await self._server.publish_event(event, thread=thread)
        except RecipientNotMemberError as exc:
            return _error("recipient_not_member", str(exc))
        return {"event": appended.model_dump(mode="json", by_alias=True)}

    async def on_run_cancel(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        identity = await _identity(self, sid)
        run_id = data.get("run_id")
        if not isinstance(run_id, str):
            return _error("invalid_request", "run_id required")

        run = await self._server.store.get_run(run_id)
        if run is None:
            return _error("not_found", "run not found")
        thread = await self._server.store.get_thread(run.thread_id)
        if thread is None or not matches(thread.tenant, _identity_tenant(identity)):
            return _error("not_found", "run not found")
        if not await self._check_namespace_match(sid, thread.tenant):
            return _error("not_found", "run not found")
        if not await self._server.check_authorize(identity, run.thread_id, "run.cancel"):
            return _error("forbidden", "not authorized: run.cancel")
        await self._server.cancel_run(run_id=run_id)
        return {"run_id": run_id, "cancelled": True}

    async def on_event_send(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        identity = await _identity(self, sid)
        thread_id = data.get("thread_id")
        raw_event = data.get("event")
        if not isinstance(thread_id, str) or not isinstance(raw_event, dict):
            return _error("invalid_request", "thread_id and event required")

        raw_event = {
            **raw_event,
            "id": raw_event.get("id") or f"evt_{secrets.token_hex(8)}",
            "thread_id": thread_id,
            "author": identity.model_dump(mode="json"),
            "created_at": raw_event.get("created_at") or datetime.now(UTC).isoformat(),
        }

        try:
            event = parse_event(raw_event)
        except ValidationError as exc:
            return _error("invalid_request", f"event validation failed: {exc}")

        if event.type in _SERVER_LIFECYCLE_TYPES:
            return _error("forbidden", f"clients cannot emit {event.type} events")

        access = await self._access_check(sid, identity, thread_id, action=f"{event.type}.send")
        if isinstance(access, dict):
            return access

        try:
            appended = await self._server.publish_event(event, thread=access)
        except RecipientNotMemberError as exc:
            return _error("recipient_not_member", str(exc))
        return {"event": appended.model_dump(mode="json", by_alias=True)}

    async def on_run_begin(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        identity = await _identity(self, sid)
        thread_id = data.get("thread_id")
        triggered_by_event_id = data.get("triggered_by_event_id")
        idempotency_key = data.get("idempotency_key")
        if not isinstance(thread_id, str):
            return _error("invalid_request", "thread_id required")

        access = await self._access_check(sid, identity, thread_id, action="run.begin")
        if isinstance(access, dict):
            return access

        triggered_by_identity = identity
        if isinstance(triggered_by_event_id, str):
            source_event = await self._server.store.get_event(triggered_by_event_id)
            if source_event is not None and source_event.thread_id == thread_id:
                triggered_by_identity = source_event.author

        run = await self._server.begin_run(
            thread=access,
            actor=identity,
            triggered_by=triggered_by_identity,
            idempotency_key=idempotency_key if isinstance(idempotency_key, str) else None,
        )
        return {"run_id": run.id, "status": run.status}

    async def on_run_end(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        identity = await _identity(self, sid)
        run_id = data.get("run_id")
        error_raw = data.get("error")
        if not isinstance(run_id, str):
            return _error("invalid_request", "run_id required")

        run = await self._server.store.get_run(run_id)
        if run is None:
            return _error("not_found", "run not found")
        if run.actor.id != identity.id:
            return _error("forbidden", "can only end your own runs")

        error: RunError | None = None
        if isinstance(error_raw, dict):
            error = RunError(
                code=str(error_raw.get("code", "error")),
                message=str(error_raw.get("message", "")),
            )

        final = await self._server.end_run(run_id=run_id, error=error)
        return {"run_id": final.id, "status": final.status}

    async def on_stream_start(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        identity = await _identity(self, sid)
        thread_id = data.get("thread_id")
        if not isinstance(thread_id, str):
            return _error("invalid_request", "thread_id required")
        access = await self._access_check(sid, identity, thread_id, action="stream.send")
        if isinstance(access, dict):
            return access
        try:
            frame = StreamStartFrame.model_validate(data)
        except ValidationError as exc:
            return _error("invalid_request", str(exc))
        # Cache the authorized thread in the session keyed by event_id so that
        # on_stream_delta and on_stream_end can skip _access_check entirely —
        # each delta would otherwise cost 2 DB round-trips (get_thread +
        # membership) for data unchanged since stream:start.
        #
        # python-socketio's get_session returns the live in-process dict (not a
        # copy); mutating `active` here is immediately visible to concurrent
        # frames on the same sid. save_session is the explicit write barrier
        # but is not the only thing preserving the mutation. If anyone "cleans
        # up" by deep-copying, concurrent streams will silently lose updates.
        session = await self.get_session(sid)
        active: dict[str, Any] = session.setdefault("active_streams", {})
        active[frame.event_id] = access
        await self.save_session(sid, session)
        await self._server.broadcast_stream_start(frame, thread=access)
        return {"ok": True}

    async def on_stream_delta(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        # Validate the frame BEFORE session lookup so malformed frames return
        # invalid_request, not not_found.
        thread_id = data.get("thread_id")
        if not isinstance(thread_id, str):
            return _error("invalid_request", "thread_id required")
        try:
            frame = StreamDeltaFrame.model_validate(data)
        except ValidationError as exc:
            return _error("invalid_request", str(exc))
        session = await self.get_session(sid)
        access = session.get("active_streams", {}).get(frame.event_id)
        if access is None:
            return _error("not_found", "stream not started or already ended")
        await self._server.broadcast_stream_delta(frame, thread=access)
        return {"ok": True}

    async def on_stream_end(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        # Validate the frame BEFORE session lookup so malformed frames return
        # invalid_request, not not_found.
        thread_id = data.get("thread_id")
        if not isinstance(thread_id, str):
            return _error("invalid_request", "thread_id required")
        try:
            frame = StreamEndFrame.model_validate(data)
        except ValidationError as exc:
            return _error("invalid_request", str(exc))
        session = await self.get_session(sid)
        active: dict[str, Any] = session.get("active_streams", {})
        access = active.pop(frame.event_id, None)
        if access is None:
            return _error("not_found", "stream not started or already ended")
        await self.save_session(sid, session)
        await self._server.broadcast_stream_end(frame, thread=access)
        return {"ok": True}

    async def _access_check(
        self,
        sid: str,
        identity: Identity,
        thread_id: str,
        *,
        action: str,
    ) -> Any:
        thread = await self._server.store.get_thread(thread_id)
        if thread is None or not matches(thread.tenant, _identity_tenant(identity)):
            return _error("not_found", "thread not found")
        if not await self._check_namespace_match(sid, thread.tenant):
            return _error("not_found", "thread not found")
        if not await self._server.check_authorize(identity, thread_id, action):
            return _error("forbidden", f"not authorized: {action}")
        return thread


class ChatSocketIO:
    def __init__(self, server: ChatServer, replay_cap: int = DEFAULT_REPLAY_CAP) -> None:
        self._server = server
        self._replay_cap = replay_cap
        # When namespace_keys is set, register under the wildcard "*" so
        # python-socketio routes every dynamic `/A`, `/A/ws_X`, etc. to this
        # namespace. Otherwise stay on the default `/` path.
        wildcard = server.namespace_keys is not None
        self._sio = socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins="*",
            # `namespaces="*"` tells python-socketio's _handle_connect to
            # accept any dynamic namespace path; without it, only paths
            # explicitly listed (default `["/"]`) are allowed.
            namespaces="*" if wildcard else None,
        )
        self._socketio_path = "/chat/ws"
        ns_path = "*" if wildcard else "/"
        self._namespace = ThreadNamespace(ns_path, server=server, replay_cap=replay_cap)
        self._sio.register_namespace(self._namespace)

    @property
    def sio(self) -> socketio.AsyncServer:
        return self._sio

    def asgi_app(self, other_asgi_app: Any = None) -> Any:
        inner = socketio.ASGIApp(self._sio, other_asgi_app, socketio_path=self._socketio_path)
        return _suppress_ws_shutdown_cancel(inner)


def _suppress_ws_shutdown_cancel(inner: Any) -> Any:
    async def app(scope: dict[str, Any], receive: Any, send: Any) -> Any:
        try:
            return await inner(scope, receive, send)
        except asyncio.CancelledError:
            if scope.get("type") == "websocket":
                return None
            raise

    return app


def _build_handshake(environ: dict[str, Any], auth: Any) -> HandshakeData:
    headers: dict[str, str] = {}
    for key, value in environ.items():
        if key.startswith("HTTP_") and isinstance(value, str):
            name = key[5:].replace("_", "-").lower()
            headers[name] = value
    return HandshakeData(
        headers=headers,
        auth=auth if isinstance(auth, dict) else {},
    )


async def _identity(ns: socketio.AsyncNamespace, sid: str) -> Identity:
    session = await ns.get_session(sid)
    identity: Identity = session["identity"]
    return identity


def _identity_tenant(identity: Identity) -> dict[str, str]:
    raw = identity.metadata.get("tenant", {})
    if not isinstance(raw, dict):
        return {}
    # See the comment on `identity_tenant` in server/rest/deps.py — non-string
    # tenant values are dropped rather than coerced via str(), mirroring the
    # strict isinstance check inside derive_namespace_path.
    return {k: v for k, v in raw.items() if isinstance(v, str)}


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}
