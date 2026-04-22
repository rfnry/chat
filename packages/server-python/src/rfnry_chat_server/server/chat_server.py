from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from rfnry_chat_protocol import (
    Event,
    Identity,
    Run,
    RunError,
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

from rfnry_chat_server.broadcast.protocol import Broadcaster
from rfnry_chat_server.handler.dispatcher import HandlerDispatcher
from rfnry_chat_server.handler.registry import HandlerRegistry
from rfnry_chat_server.handler.types import HandlerCallable
from rfnry_chat_server.recipients import RecipientNotMemberError, normalize_recipients
from rfnry_chat_server.server.auth import AuthenticateCallback, AuthorizeCallback, HandshakeData
from rfnry_chat_server.server.namespace import NamespaceViolation, derive_namespace_path
from rfnry_chat_server.server.run_events import (
    run_cancelled as _run_cancelled_event,
)
from rfnry_chat_server.server.run_events import (
    run_completed as _run_completed_event,
)
from rfnry_chat_server.server.run_events import (
    run_failed as _run_failed_event,
)
from rfnry_chat_server.server.run_events import (
    run_started as _run_started_event,
)
from rfnry_chat_server.store.protocol import ChatStore

_log = logging.getLogger(__name__)


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
    ) -> None:
        self.store = store
        self.authenticate = authenticate or _identity_from_handshake
        self.authorize = authorize
        self.replay_cap = replay_cap
        self.broadcaster = broadcaster
        self.namespace_keys = _validate_namespace_keys(namespace_keys)
        self.run_timeout_seconds = run_timeout_seconds
        self.watchdog_interval_seconds = watchdog_interval_seconds
        self._socketio: Any = None
        self._system_identity = system_identity or SystemIdentity(id="system", name="system")
        self._handlers = HandlerRegistry()
        self._handler_dispatcher = HandlerDispatcher(
            server=self,
            registry=self._handlers,
            system_identity=self._system_identity,
        )
        self._watchdog_task: asyncio.Task[None] | None = None

        from rfnry_chat_server.server.rest.members import build_router as build_members
        from rfnry_chat_server.server.rest.messages import build_router as build_messages
        from rfnry_chat_server.server.rest.runs import build_router as build_runs
        from rfnry_chat_server.server.rest.threads import build_router as build_threads

        self.router = APIRouter()
        self.router.include_router(build_threads())
        self.router.include_router(build_messages())
        self.router.include_router(build_members())
        self.router.include_router(build_runs())

    async def start(self) -> None:
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
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
        threshold = datetime.now(UTC) - timedelta(seconds=self.run_timeout_seconds)
        stale = await self.store.find_runs_started_before(
            statuses=("pending", "running"),
            threshold=threshold,
        )
        for run in stale:
            try:
                await self.end_run(
                    run_id=run.id,
                    error=RunError(
                        code="timeout",
                        message=f"run exceeded {self.run_timeout_seconds}s without end signal",
                    ),
                )
            except Exception:
                _log.exception("watchdog failed to timeout run %s", run.id)

    def on(
        self,
        event_type: str,
        *,
        tool: str | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator(event_type, tool=tool)

    def on_message(self) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("message")

    def on_reasoning(self) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("reasoning")

    def on_tool_call(self, name: str) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("tool.call", tool=name)

    def on_tool_result(self) -> Callable[[HandlerCallable], HandlerCallable]:
        return self._handlers.decorator("tool.result")

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
        if event.recipients is not None:
            normalized = normalize_recipients(event.recipients, author_id=event.author.id)
            if normalized != event.recipients:
                event = event.model_copy(update={"recipients": normalized})
            if normalized:
                members = await self.store.list_members(event.thread_id)
                member_ids = {m.identity_id for m in members}
                for rid in normalized:
                    if rid not in member_ids:
                        raise RecipientNotMemberError(rid)

        appended = await self.store.append_event(event)
        if self.broadcaster is not None:
            namespace: str | None = None
            if self.namespace_keys is not None:
                if thread is None:
                    thread = await self.store.get_thread(event.thread_id)
                if thread is not None:
                    namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
            await self.broadcaster.broadcast_event(appended, namespace=namespace)

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
        namespace: str | None = None
        if self.namespace_keys is not None:
            namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
        tenant_path = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
        room = f"tenant:{tenant_path}"
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
        namespace: str | None = None
        if self.namespace_keys is not None:
            namespace = derive_namespace_path(tenant, namespace_keys=self.namespace_keys)
        tenant_path = derive_namespace_path(tenant, namespace_keys=self.namespace_keys)
        room = f"tenant:{tenant_path}"
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

        existing_active = await self.store.find_active_run(thread.id, actor_id=actor.id)
        if existing_active is not None:
            return existing_active

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
        updated = await self.store.update_run_status(run_id, "cancelled")
        thread = await self.store.get_thread(updated.thread_id)
        if thread is not None:
            await self.publish_run_updated(updated, thread=thread)
            await self.publish_event(_run_cancelled_event(updated, thread, updated.actor), thread=thread)
        return updated

    async def end_run(self, *, run_id: str, error: RunError | None) -> Run:
        if error is None:
            updated = await self.store.update_run_status(run_id, "completed")
            thread = await self.store.get_thread(updated.thread_id)
            if thread is not None:
                await self.publish_run_updated(updated, thread=thread)
                await self.publish_event(_run_completed_event(updated, thread, updated.actor), thread=thread)
            return updated
        updated = await self.store.update_run_status(run_id, "failed", error=error)
        thread = await self.store.get_thread(updated.thread_id)
        if thread is not None:
            await self.publish_run_updated(updated, thread=thread)
            await self.publish_event(_run_failed_event(updated, thread, updated.actor, error), thread=thread)
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

    def mount_socketio(self, fastapi_app: Any) -> Any:
        from rfnry_chat_server.broadcast.socketio import SocketIOBroadcaster
        from rfnry_chat_server.socketio.server import ChatSocketIO

        sio_server = ChatSocketIO(self, replay_cap=self.replay_cap)
        self.broadcaster = SocketIOBroadcaster(sio_server.sio)
        self._socketio = sio_server
        return sio_server.asgi_app(fastapi_app)
