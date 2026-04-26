from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from rfnry_chat_protocol import (
    Event,
    Identity,
    MessageEvent,
    Run,
    RunError,
    RunStatus,
    StreamDeltaFrame,
    StreamEndFrame,
    StreamStartFrame,
    SystemIdentity,
    TenantScope,
    Thread,
    ThreadInvitedFrame,
    ThreadMember,
    parse_identity,
)

from rfnry_chat_server.auth import AuthenticateCallback, AuthorizeCallback, HandshakeData
from rfnry_chat_server.broadcast.protocol import Broadcaster
from rfnry_chat_server.handler.dispatcher import HandlerDispatcher
from rfnry_chat_server.handler.registry import HandlerRegistry
from rfnry_chat_server.handler.types import HandlerCallable
from rfnry_chat_server.mentions import extract_text, parse_mention_ids
from rfnry_chat_server.namespace import NamespaceViolation, derive_namespace_path
from rfnry_chat_server.presence import PresenceRegistry
from rfnry_chat_server.recipients import RecipientNotMemberError, normalize_recipients
from rfnry_chat_server.run_events import (
    run_cancelled as _run_cancelled_event,
)
from rfnry_chat_server.run_events import (
    run_completed as _run_completed_event,
)
from rfnry_chat_server.run_events import (
    run_failed as _run_failed_event,
)
from rfnry_chat_server.run_events import (
    run_started as _run_started_event,
)
from rfnry_chat_server.store.protocol import ChatStore

_log = logging.getLogger(__name__)


class _LifespanNoiseFilter(logging.Filter):
    """Silence uvicorn.error's "Exception in 'lifespan' protocol" log when
    the underlying exception is CancelledError.

    Background: a consumer's lifespan may open an outbound socketio-client
    (e.g. via `rfnry_chat_client.ChatClient.running()`). The client's
    background aiohttp tasks prevent uvicorn from reaching its normal
    graceful shutdown on SIGINT, causing the lifespan task to be cancelled
    at `await receive()`. Starlette logs this via uvicorn.error — cosmetic,
    exit code remains 0.

    Duplicated from rfnry_chat_client.client to keep the one-way import
    rule (server must not import client). Kept in lockstep.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.msg, str):
            return True

        if record.msg.startswith("Exception in 'lifespan' protocol"):
            exc_type = record.exc_info[0] if record.exc_info else None
            if exc_type is None:
                return True
            try:
                is_cancelled = issubclass(exc_type, asyncio.CancelledError)
            except TypeError:
                is_cancelled = False
            return not is_cancelled

        if record.msg.startswith("Traceback (most recent call last):") and "CancelledError" in record.msg:
            return False

        return True


_LIFESPAN_NOISE_FILTER_INSTALLED = False


def _install_lifespan_noise_filter() -> None:
    global _LIFESPAN_NOISE_FILTER_INSTALLED
    if _LIFESPAN_NOISE_FILTER_INSTALLED:
        return
    logging.getLogger("uvicorn.error").addFilter(_LifespanNoiseFilter())
    _LIFESPAN_NOISE_FILTER_INSTALLED = True


def _validate_namespace_keys(namespace_keys: list[str] | None) -> list[str] | None:
    if namespace_keys is None:
        return None
    if not namespace_keys:
        raise NamespaceViolation("namespace_keys must be None or a non-empty list")
    seen: set[str] = set()
    for key in namespace_keys:
        if not key:
            raise NamespaceViolation("namespace_keys contains an empty key")
        if key in seen:
            raise NamespaceViolation(f"namespace_keys contains duplicate: {key!r}")
        seen.add(key)
    return list(namespace_keys)


IDENTITY_HEADER = "x-rfnry-identity"


async def _identity_from_handshake(handshake: HandshakeData) -> Identity | None:
    raw = handshake.auth.get("identity")
    if not isinstance(raw, dict):
        encoded = handshake.headers.get(IDENTITY_HEADER, "")
        if not encoded:
            return None
        import base64
        import json as _json

        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            raw = _json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
    try:
        return parse_identity(raw)
    except Exception:
        return None


class ChatServer:
    def __init__(
        self,
        *,
        store: ChatStore,
        authenticate: AuthenticateCallback | None = None,
        authorize: AuthorizeCallback | None = None,
        replay_cap: int = 500,
        broadcaster: Broadcaster | None = None,
        namespace_keys: list[str] | None = None,
        system_identity: SystemIdentity | None = None,
        run_timeout_seconds: int = 120,
        watchdog_interval_seconds: float = 30.0,
        watchdog_batch_size: int = 100,
    ) -> None:
        self.store = store
        self._authenticate_is_default = authenticate is None
        self.authenticate = authenticate or _identity_from_handshake
        self.authorize = authorize
        self.replay_cap = replay_cap
        self.broadcaster = broadcaster
        self.presence = PresenceRegistry()
        self.namespace_keys = _validate_namespace_keys(namespace_keys)
        self.run_timeout_seconds = run_timeout_seconds
        self.watchdog_interval_seconds = watchdog_interval_seconds
        self.watchdog_batch_size = watchdog_batch_size
        self._socketio: Any = None
        self._system_identity = system_identity or SystemIdentity(id="system", name="system")
        self._handlers = HandlerRegistry()
        self._handler_dispatcher = HandlerDispatcher(
            server=self,
            registry=self._handlers,
            system_identity=self._system_identity,
        )
        self._watchdog_task: asyncio.Task[None] | None = None

        from rfnry_chat_server.transport.rest.members import build_router as build_members
        from rfnry_chat_server.transport.rest.messages import build_router as build_messages
        from rfnry_chat_server.transport.rest.presence import build_router as build_presence
        from rfnry_chat_server.transport.rest.runs import build_router as build_runs
        from rfnry_chat_server.transport.rest.threads import build_router as build_threads

        self.router = APIRouter()
        self.router.include_router(build_threads())
        self.router.include_router(build_messages())
        self.router.include_router(build_members())
        self.router.include_router(build_runs())
        self.router.include_router(build_presence())

    async def start(self) -> None:
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        if self._authenticate_is_default:
            _log.warning(
                "ChatServer started without an authenticate= callback; "
                "the default trusts client-supplied identity and is NOT "
                "safe for production. Pass authenticate= to verify "
                "credentials (e.g. JWT, session cookie)."
            )
        await self.store.ensure_schema()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop(self) -> None:
        if self._socketio is not None:
            with contextlib.suppress(BaseException):
                await self._socketio.sio.shutdown()

        task = self._watchdog_task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            self._watchdog_task = None

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """Async context manager for running this ChatServer alongside a
        FastAPI app's lifespan.

        Plug this into your FastAPI lifespan:

            @asynccontextmanager
            async def lifespan(app):
                async with chat_server.running():
                    yield

        Calls `start()` on enter and `stop()` on exit. Handles the watchdog
        task lifecycle transparently so consumers don't need to remember
        the pair.
        """
        await self.start()
        try:
            yield
        finally:
            await self.stop()

    def serve(
        self,
        app: Any,
        *,
        router_prefix: str = "/chat",
        **uvicorn_kwargs: Any,
    ) -> None:
        """Run a FastAPI (or other ASGI) app under uvicorn with this
        ChatServer mounted + lifecycle wired up.

        Internally:
          1. Wraps `app.router.lifespan_context` with `running()` so
             `start()` / `stop()` run around the app's existing lifespan.
          2. Includes `self.router` at `router_prefix` (default "/chat").
          3. Wraps the app with Socket.IO via `mount()`.
          4. Calls `uvicorn.run(asgi_app, **uvicorn_kwargs)`.

        All uvicorn kwargs (host, port, workers, ssl_*, log_config, etc.)
        pass through to uvicorn.run.

        **Route-override ordering:** Consumer-defined routes registered
        on `app` BEFORE calling `serve()` will win over the library's
        router (FastAPI first-match routing). This is the natural
        ordering when using @app.get/@app.post decorators at module
        load — `serve()` is called at the bottom of your main script
        after all decorators have registered.

        Usage:

            if __name__ == "__main__":
                chat_server.serve(app, host="0.0.0.0", port=8000)
        """
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def _wrapped_lifespan(inner_app: Any) -> AsyncIterator[Any]:
            async with self.running():
                async with original_lifespan(inner_app) as maybe_state:
                    yield maybe_state

        app.router.lifespan_context = _wrapped_lifespan

        app.include_router(self.router, prefix=router_prefix)
        asgi = self.mount(app)

        # Defensive: if the consumer's lifespan spins up an outbound
        # socketio-client (e.g. via `chat_client.running()`), uvicorn 0.46+
        # propagates CancelledError on SIGINT. Silence it here the same way
        # rfnry_chat_client.serve() does (duplicated to keep the one-way
        # import rule: server must not import client).
        _install_lifespan_noise_filter()

        import uvicorn

        try:
            uvicorn.run(asgi, **uvicorn_kwargs)
        except asyncio.CancelledError:
            pass

    async def _watchdog_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.watchdog_interval_seconds)
                await self._sweep_stale_runs()
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("watchdog sweep failed; continuing")

    async def _sweep_stale_runs(self) -> None:
        async def _timeout_one(run_id: str) -> None:
            try:
                await self.end_run(
                    run_id=run_id,
                    error=RunError(
                        code="timeout",
                        message=f"run exceeded {self.run_timeout_seconds}s without end signal",
                    ),
                )
            except Exception:
                _log.exception("watchdog failed to timeout run %s", run_id)

        while True:
            threshold = datetime.now(UTC) - timedelta(seconds=self.run_timeout_seconds)
            stale = await self.store.find_runs_started_before(
                threshold=threshold,
                limit=self.watchdog_batch_size,
            )
            if not stale:
                return

            await asyncio.gather(*(_timeout_one(run.id) for run in stale))
            if len(stale) < self.watchdog_batch_size:
                return

    def on(
        self,
        event_type: str,
        *,
        tool: str | None = None,
        lazy_run: bool = False,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator(event_type, tool=tool, lazy_run=lazy_run)

    def on_message(self, *, lazy_run: bool = False) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("message", lazy_run=lazy_run)

    def on_reasoning(self, *, lazy_run: bool = False) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("reasoning", lazy_run=lazy_run)

    def on_tool_call(self, name: str, *, lazy_run: bool = False) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("tool.call", tool=name, lazy_run=lazy_run)

    def on_tool_result(self, *, lazy_run: bool = False) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("tool.result", lazy_run=lazy_run)

    def on_any_event(self, *, lazy_run: bool = False) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("*", lazy_run=lazy_run)

    async def check_authorize(
        self,
        identity: Identity,
        thread_id: str,
        action: str,
        *,
        target_id: str | None = None,
    ) -> bool:
        if self.authorize is None:
            # Default policy: membership is the gate. Historically this check was
            # hardcoded in every REST/socket handler next to matches(); moving it
            # here makes access policy a single replaceable function. Consumers
            # that want "tenant alone is enough" (e.g. workspace-is-the-room)
            # pass their own `authorize=` callback.
            return await self.store.is_member(thread_id, identity.id)
        return await self.authorize(identity, thread_id, action, target_id=target_id)

    async def publish_event(self, event: Event, *, thread: Thread | None = None) -> Event:
        members: list[ThreadMember] | None = None
        if isinstance(event, MessageEvent) and event.recipients is None:
            text = extract_text(event.content)
            if text and "@" in text:
                members = await self.store.list_members(event.thread_id)
                member_ids = {m.identity_id for m in members}
                ids = parse_mention_ids(text, member_ids)
                if ids:
                    event = event.model_copy(update={"recipients": ids})

        if event.recipients is not None:
            normalized = normalize_recipients(event.recipients, author_id=event.author.id)
            if normalized != event.recipients:
                event = event.model_copy(update={"recipients": normalized})
            if normalized:
                if members is None:
                    members = await self.store.list_members(event.thread_id)
                member_ids = {m.identity_id for m in members}
                for rid in normalized:
                    if rid not in member_ids:
                        raise RecipientNotMemberError(rid)

        namespace: str | None = None
        if self.broadcaster is not None and self.namespace_keys is not None:
            if thread is None:
                thread = await self.store.get_thread(event.thread_id)
            if thread is not None:
                namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)

        # Pipeline the DB write and the broadcast. The broadcast doesn't depend
        # on the write completing — it carries the event payload directly. Total
        # latency drops from write+broadcast to max(write, broadcast).
        #
        # Error-path note: if append_event raises, asyncio.gather propagates the
        # exception but does NOT cancel the in-flight broadcast (default
        # return_exceptions=False semantics). The broadcast may still complete
        # and reach live subscribers, producing a "ghost event" they see on
        # WebSocket but won't find in REST history. Accepted as the cost of
        # parallelization — DB write failures are rare and the WebSocket
        # subscriber will reconcile on reconnect/replay.
        if self.broadcaster is not None:
            appended, _ = await asyncio.gather(
                self.store.append_event(event),
                self.broadcaster.broadcast_event(event, namespace=namespace),
            )
        else:
            appended = await self.store.append_event(event)

        if thread is None:
            thread = await self.store.get_thread(appended.thread_id)
        if thread is not None:
            asyncio.create_task(self._handler_dispatcher.dispatch(appended, thread))

        return appended

    async def publish_thread_updated(self, thread: Thread) -> None:
        if self.broadcaster is not None:
            namespace: str | None = None
            if self.namespace_keys is not None:
                namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
            await self.broadcaster.broadcast_thread_updated(thread, namespace=namespace)

    async def publish_thread_cleared(
        self,
        thread_id: str,
        *,
        thread: Thread | None = None,
    ) -> None:
        if self.broadcaster is None:
            return
        namespace: str | None = None
        if self.namespace_keys is not None:
            if thread is None:
                thread = await self.store.get_thread(thread_id)
            if thread is not None:
                namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
        await self.broadcaster.broadcast_thread_cleared(thread_id, namespace=namespace)

    async def publish_thread_created(self, thread: Thread) -> None:
        """Fan thread:created to every connected socket whose identity tenant
        matches the new thread, via the deterministic tenant room joined at
        connect time."""
        if self.broadcaster is None:
            return
        tenant_path = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
        room = f"tenant:{tenant_path}"
        namespace = tenant_path if self.namespace_keys is not None else None
        await self.broadcaster.broadcast_thread_created(
            thread,
            room=room,
            namespace=namespace,
        )

    async def publish_thread_deleted(self, thread_id: str, tenant: TenantScope) -> None:
        """Fan thread:deleted to the tenant room. Tenant is passed explicitly
        because the row is gone by the time we broadcast."""
        if self.broadcaster is None:
            return
        tenant_path = derive_namespace_path(tenant, namespace_keys=self.namespace_keys)
        room = f"tenant:{tenant_path}"
        namespace = tenant_path if self.namespace_keys is not None else None
        await self.broadcaster.broadcast_thread_deleted(
            thread_id,
            tenant,
            room=room,
            namespace=namespace,
        )

    async def publish_members_updated(
        self,
        thread_id: str,
        members: list[Identity],
        *,
        thread: Thread | None = None,
    ) -> None:
        if self.broadcaster is not None:
            namespace: str | None = None
            if self.namespace_keys is not None:
                if thread is None:
                    thread = await self.store.get_thread(thread_id)
                if thread is not None:
                    namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
            await self.broadcaster.broadcast_members_updated(thread_id, members, namespace=namespace)

    async def publish_thread_invited(
        self,
        thread: Thread,
        *,
        added_member: Identity,
        added_by: Identity,
    ) -> None:
        if self.broadcaster is None:
            return
        if added_member.id == added_by.id:
            return
        namespace: str | None = None
        if self.namespace_keys is not None:
            namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
        frame = ThreadInvitedFrame(
            thread=thread,
            added_member=added_member,
            added_by=added_by,
        )
        await self.broadcaster.broadcast_thread_invited(frame, namespace=namespace)

    async def publish_run_updated(self, run: Run, *, thread: Thread | None = None) -> None:
        if self.broadcaster is not None:
            namespace: str | None = None
            if self.namespace_keys is not None:
                if thread is None:
                    thread = await self.store.get_thread(run.thread_id)
                if thread is not None:
                    namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
            await self.broadcaster.broadcast_run_updated(run, namespace=namespace)

    async def begin_run(
        self,
        *,
        thread: Thread,
        actor: Identity,
        triggered_by: Identity,
        idempotency_key: str | None,
    ) -> Run:
        # Explicit reuse mechanism: if the caller supplies an idempotency_key,
        # return the existing run. This is the ONLY supported reuse path.
        # Previously we also silently returned any active run for the same
        # (thread, actor) pair via find_active_run — that violated the
        # caller's mental model ("each begin_run yields its own run") and
        # produced phantom run.started/run.completed fan-out in multi-agent
        # channels. Callers that want de-duplication should pass an
        # idempotency_key explicitly.
        if idempotency_key is not None:
            existing = await self.store.find_run_by_idempotency_key(thread.id, idempotency_key)
            if existing is not None:
                return existing

        run = Run(
            id=f"run_{secrets.token_hex(8)}",
            thread_id=thread.id,
            actor=actor,
            triggered_by=triggered_by,
            status="running",
            started_at=datetime.now(UTC),
            idempotency_key=idempotency_key,
        )
        created = await self.store.create_run(run)
        await self.publish_run_updated(created, thread=thread)
        await self.publish_event(_run_started_event(created, thread, actor), thread=thread)
        return created

    async def cancel_run(self, *, run_id: str) -> Run:
        updated = await self.store.update_run_status_if_active(run_id, "cancelled")
        if updated is None:
            # Already terminal (idempotent) or missing.
            existing = await self.store.get_run(run_id)
            if existing is None:
                raise LookupError(f"run not found: {run_id}")
            return existing
        thread = await self.store.get_thread(updated.thread_id)
        if thread is not None:
            await self.publish_run_updated(updated, thread=thread)
            await self.publish_event(_run_cancelled_event(updated, thread, updated.actor), thread=thread)
        return updated

    async def end_run(self, *, run_id: str, error: RunError | None) -> Run:
        target_status: RunStatus = "completed" if error is None else "failed"
        updated = await self.store.update_run_status_if_active(run_id, target_status, error=error)
        if updated is None:
            # Already terminal — idempotent no-op, no publish.
            existing = await self.store.get_run(run_id)
            if existing is None:
                raise LookupError(f"run not found: {run_id}")
            return existing
        thread = await self.store.get_thread(updated.thread_id)
        if thread is not None:
            await self.publish_run_updated(updated, thread=thread)
            event = (
                _run_completed_event(updated, thread, updated.actor)
                if error is None
                else _run_failed_event(updated, thread, updated.actor, error)
            )
            await self.publish_event(event, thread=thread)
        return updated

    async def broadcast_stream_start(self, frame: StreamStartFrame, *, thread: Thread) -> None:
        if self.broadcaster is None:
            return
        namespace = self.namespace_for_thread(thread)
        await self.broadcaster.broadcast_stream_start(frame, namespace=namespace)

    async def broadcast_stream_delta(self, frame: StreamDeltaFrame, *, thread: Thread) -> None:
        if self.broadcaster is None:
            return
        namespace = self.namespace_for_thread(thread)
        await self.broadcaster.broadcast_stream_delta(frame, namespace=namespace)

    async def broadcast_stream_end(self, frame: StreamEndFrame, *, thread: Thread) -> None:
        if self.broadcaster is None:
            return
        namespace = self.namespace_for_thread(thread)
        await self.broadcaster.broadcast_stream_end(frame, namespace=namespace)

    def namespace_for_thread(self, thread: Thread) -> str | None:
        if self.namespace_keys is None:
            return None
        return derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)

    def enforce_namespace_on_identity(self, identity: Identity) -> None:
        if self.namespace_keys is None:
            return
        tenant_raw = identity.metadata.get("tenant", {})
        if not isinstance(tenant_raw, dict):
            tenant: dict[str, str] = {}
        else:
            # Drop non-string values rather than coercing via str(), so that
            # a consumer accidentally storing a bool/number/list cannot
            # silently pass validation — derive_namespace_path will raise a
            # clear "missing required key" error on the dropped key instead.
            tenant = {k: v for k, v in tenant_raw.items() if isinstance(v, str)}
        derive_namespace_path(tenant, namespace_keys=self.namespace_keys)

    def mount(
        self,
        fastapi_app: Any,
        *,
        cors_allowed_origins: str | list[str] = "*",
        ping_interval: float = 20,
        ping_timeout: float = 20,
    ) -> Any:
        from rfnry_chat_server.broadcast.socketio import SocketIOBroadcaster
        from rfnry_chat_server.transport.socket.server import SocketTransport

        sio_server = SocketTransport(
            self,
            replay_cap=self.replay_cap,
            cors_allowed_origins=cors_allowed_origins,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
        )
        self.broadcaster = SocketIOBroadcaster(sio_server.sio)
        self._socketio = sio_server
        return sio_server.asgi_app(fastapi_app)
