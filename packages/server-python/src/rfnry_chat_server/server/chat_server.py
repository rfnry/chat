from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from rfnry_chat_protocol import (
    AssistantIdentity,
    Event,
    Identity,
    MessageEvent,
    Run,
    RunError,
    StreamDeltaFrame,
    StreamEndFrame,
    StreamStartFrame,
    SystemIdentity,
    Thread,
    ThreadMember,
    ToolCallEvent,
)

from rfnry_chat_server.analytics.collector import OnAnalyticsCallback
from rfnry_chat_server.broadcast.protocol import Broadcaster
from rfnry_chat_server.handler.executor import RunExecutor
from rfnry_chat_server.handler.stream import StreamSink
from rfnry_chat_server.handler.types import HandlerCallable
from rfnry_chat_server.recipients import RecipientNotMemberError, normalize_recipients
from rfnry_chat_server.server.auth import AuthenticateCallback, AuthorizeCallback
from rfnry_chat_server.server.namespace import NamespaceViolation, derive_namespace_path
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
from rfnry_chat_server.tools.registry import ToolCallHandler, ToolRegistry
from rfnry_chat_server.tools.runner import ToolRunner

MAX_AUTO_INVOKE_CHAIN_DEPTH = 8


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


class _BoundStreamSink:
    def __init__(self, server: ChatServer, thread: Thread) -> None:
        self._server = server
        self._thread = thread

    async def start(self, frame: StreamStartFrame) -> None:
        await self._server.broadcast_stream_start(frame, thread=self._thread)

    async def delta(self, frame: StreamDeltaFrame) -> None:
        await self._server.broadcast_stream_delta(frame, thread=self._thread)

    async def end(self, frame: StreamEndFrame) -> None:
        await self._server.broadcast_stream_end(frame, thread=self._thread)

    async def publish_event(self, event: Event) -> Event:
        return await self._server.publish_event(event, thread=self._thread)


class ChatServer:
    def __init__(
        self,
        *,
        store: ChatStore,
        authenticate: AuthenticateCallback,
        authorize: AuthorizeCallback | None = None,
        auto_invoke_recipients: bool = True,
        on_analytics: OnAnalyticsCallback | None = None,
        run_timeout_seconds: int = 120,
        tool_timeout_seconds: int = 30,
        replay_cap: int = 500,
        broadcaster: Broadcaster | None = None,
        namespace_keys: list[str] | None = None,
        system_identity: SystemIdentity | None = None,
    ) -> None:
        self.store = store
        self.authenticate = authenticate
        self.authorize = authorize
        self.auto_invoke_recipients = auto_invoke_recipients
        self.replay_cap = replay_cap
        self.broadcaster = broadcaster
        self.namespace_keys = _validate_namespace_keys(namespace_keys)
        self._handlers: dict[str, HandlerCallable] = {}
        self._socketio: Any = None
        self._tool_registry = ToolRegistry()
        self._system_identity = system_identity or SystemIdentity(id="system", name="system")
        self._tool_runner = ToolRunner(
            registry=self._tool_registry,
            server=self,
            timeout_seconds=tool_timeout_seconds,
            system_identity=self._system_identity,
        )
        self.executor = RunExecutor(
            store=store,
            on_analytics=on_analytics,
            run_timeout_seconds=run_timeout_seconds,
            publish_event=self.publish_event,
            publish_thread_updated=self.publish_thread_updated,
            handler_resolver=self.get_handler,
            stream_sink_factory=self._make_stream_sink,
        )

        from rfnry_chat_server.server.rest.invocations import build_router as build_invocations
        from rfnry_chat_server.server.rest.members import build_router as build_members
        from rfnry_chat_server.server.rest.messages import build_router as build_messages
        from rfnry_chat_server.server.rest.runs import build_router as build_runs
        from rfnry_chat_server.server.rest.threads import build_router as build_threads

        self.router = APIRouter()
        self.router.include_router(build_threads())
        self.router.include_router(build_messages())
        self.router.include_router(build_members())
        self.router.include_router(build_invocations())
        self.router.include_router(build_runs())

    def register_assistant(self, assistant_id: str, handler: HandlerCallable) -> None:
        self._handlers[assistant_id] = handler

    def assistant(self, assistant_id: str) -> Callable[[HandlerCallable], HandlerCallable]:
        def decorator(handler: HandlerCallable) -> HandlerCallable:
            self.register_assistant(assistant_id, handler)
            return handler

        return decorator

    def get_handler(self, assistant_id: str) -> HandlerCallable | None:
        return self._handlers.get(assistant_id)

    def on_tool_call(self, name: str) -> Callable[[ToolCallHandler], ToolCallHandler]:
        return self._tool_registry.decorator(name)

    async def check_authorize(
        self,
        identity: Identity,
        thread_id: str,
        action: str,
        *,
        target_id: str | None = None,
    ) -> bool:
        if self.authorize is None:
            return True
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

        if self.auto_invoke_recipients and isinstance(appended, MessageEvent) and appended.recipients:
            if thread is None:
                thread = await self.store.get_thread(appended.thread_id)
            if thread is not None:
                if members is None:
                    members = await self.store.list_members(appended.thread_id)
                await self._auto_invoke_recipients(
                    event=appended,
                    members=members,
                    thread=thread,
                )

        if (
            isinstance(appended, ToolCallEvent)
            and self._tool_registry.get(appended.tool.name) is not None
        ):
            if thread is None:
                thread = await self.store.get_thread(appended.thread_id)
            if thread is not None:
                asyncio.create_task(self._tool_runner.handle(appended, thread))

        return appended

    async def _auto_invoke_recipients(
        self,
        *,
        event: MessageEvent,
        members: list[ThreadMember],
        thread: Thread,
    ) -> None:
        if not event.recipients:
            return

        parent_depth = 0
        if event.run_id is not None:
            parent_depth = self.executor.chain_depth_for(event.run_id)
            if parent_depth >= MAX_AUTO_INVOKE_CHAIN_DEPTH:
                return

        members_by_id = {m.identity_id: m for m in members}
        for assistant_id in event.recipients:
            handler = self.get_handler(assistant_id)
            if handler is None:
                continue
            if not await self.check_authorize(
                event.author,
                thread.id,
                "assistant.invoke",
                target_id=assistant_id,
            ):
                continue
            member = members_by_id.get(assistant_id)
            if member is None or not isinstance(member.identity, AssistantIdentity):
                continue
            await self.executor.execute(
                thread=thread,
                assistant=member.identity,
                triggered_by=event.author,
                handler=handler,
                chain_depth=parent_depth + 1,
            )

    async def publish_thread_updated(self, thread: Thread) -> None:
        if self.broadcaster is not None:
            namespace: str | None = None
            if self.namespace_keys is not None:
                namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
            await self.broadcaster.broadcast_thread_updated(thread, namespace=namespace)

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
        await self.publish_event(_run_started_event(created, thread, actor), thread=thread)
        return created

    async def end_run(self, *, run_id: str, error: RunError | None) -> Run:
        if error is None:
            updated = await self.store.update_run_status(run_id, "completed")
            thread = await self.store.get_thread(updated.thread_id)
            if thread is not None:
                await self.publish_event(
                    _run_completed_event(updated, thread, updated.actor), thread=thread
                )
            return updated
        updated = await self.store.update_run_status(run_id, "failed", error=error)
        thread = await self.store.get_thread(updated.thread_id)
        if thread is not None:
            await self.publish_event(
                _run_failed_event(updated, thread, updated.actor, error), thread=thread
            )
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

    def _make_stream_sink(self, thread: Thread) -> StreamSink:
        return _BoundStreamSink(self, thread)

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
