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
from rfnry_chat_server.members_cache import MembersCache
from rfnry_chat_server.mentions import extract_text, parse_mention_ids
from rfnry_chat_server.namespace import NamespaceViolation, derive_namespace_path
from rfnry_chat_server.observability import Observability
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
from rfnry_chat_server.send import Send
from rfnry_chat_server.store.protocol import ChatStore

_log = logging.getLogger(__name__)


class _LifespanNoiseFilter(logging.Filter):
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
        member_cache_ttl_seconds: float = 5.0,
        observability: Observability | None = None,
    ) -> None:
        self.store = store
        self._members_cache = MembersCache(store, ttl_seconds=member_cache_ttl_seconds)
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
        self.observability = observability or Observability()
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

        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def _wrapped_lifespan(inner_app: Any) -> AsyncIterator[Any]:
            async with self.running():
                async with original_lifespan(inner_app) as maybe_state:
                    yield maybe_state

        app.router.lifespan_context = _wrapped_lifespan

        app.include_router(self.router, prefix=router_prefix)
        asgi = self.mount(app)

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
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator(
            event_type,
            tool=tool,
            lazy_run=lazy_run,
            idempotency_key=idempotency_key,
        )

    def on_message(
        self,
        *,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("message", lazy_run=lazy_run, idempotency_key=idempotency_key)

    def on_reasoning(
        self,
        *,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("reasoning", lazy_run=lazy_run, idempotency_key=idempotency_key)

    def on_tool_call(
        self,
        name: str | None = None,
        *,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator(
            "tool.call",
            tool=name,
            lazy_run=lazy_run,
            idempotency_key=idempotency_key,
        )

    def on_tool_result(
        self,
        *,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("tool.result", lazy_run=lazy_run, idempotency_key=idempotency_key)

    def on_any_event(
        self,
        *,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("*", lazy_run=lazy_run, idempotency_key=idempotency_key)

    async def check_authorize(
        self,
        identity: Identity,
        thread_id: str,
        action: str,
        *,
        target_id: str | None = None,
    ) -> bool:
        if self.authorize is None:
            return await self.store.is_member(thread_id, identity.id)
        return await self.authorize(identity, thread_id, action, target_id=target_id)

    async def list_members(self, thread_id: str) -> list[ThreadMember]:
        return await self._members_cache.get(thread_id)

    def invalidate_members_cache(self, thread_id: str) -> None:
        self._members_cache.invalidate(thread_id)

    @asynccontextmanager
    async def send(
        self,
        thread_id: str,
        *,
        as_identity: Identity,
        triggered_by: Event | Identity | None = None,
        idempotency_key: str | None = None,
        lazy: bool = False,
    ) -> AsyncIterator[Send]:
        thread = await self.store.get_thread(thread_id)
        if thread is None:
            raise LookupError(f"thread not found: {thread_id}")
        if not await self.check_authorize(as_identity, thread_id, "message.send"):
            raise PermissionError(f"identity {as_identity.id} not authorized to send in {thread_id}")

        if isinstance(triggered_by, Event):
            triggered_identity: Identity = triggered_by.author
        elif triggered_by is not None:
            triggered_identity = triggered_by
        else:
            triggered_identity = as_identity

        opened_run: list[Run] = []

        async def _start_run() -> str:
            if opened_run:
                return opened_run[0].id
            run = await self.begin_run(
                thread=thread,
                actor=as_identity,
                triggered_by=triggered_identity,
                idempotency_key=idempotency_key,
            )
            opened_run.append(run)
            return run.id

        if not lazy:
            await _start_run()

        send = Send(
            thread_id=thread_id,
            author=as_identity,
            run_id=opened_run[0].id if opened_run else None,
            server=self,
            thread=thread,
            run_starter=_start_run,
        )
        try:
            yield send
        except BaseException as exc:
            if opened_run:
                await self.end_run(run_id=opened_run[0].id, error=RunError(code="send_error", message=str(exc)))
            raise
        if opened_run:
            await self.end_run(run_id=opened_run[0].id, error=None)

    async def publish_event(self, event: Event, *, thread: Thread | None = None) -> Event:
        members: list[ThreadMember] | None = None
        if isinstance(event, MessageEvent) and event.recipients is None:
            text = extract_text(event.content)
            if text and "@" in text:
                members = await self.list_members(event.thread_id)
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
                    members = await self.list_members(event.thread_id)
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
