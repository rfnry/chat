from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

import asyncpg
from rfnry_chat_protocol import (
    AssistantIdentity,
    Event,
    Identity,
    Run,
    RunCancelledEvent,
    RunCompletedEvent,
    RunError,
    RunFailedEvent,
    RunStartedEvent,
    Thread,
    ThreadPatch,
    ThreadTenantChangedEvent,
)

from rfnry_chat_server.analytics.collector import AssistantAnalytics, OnAnalyticsCallback
from rfnry_chat_server.handler.context import HandlerContext
from rfnry_chat_server.handler.send import HandlerSend
from rfnry_chat_server.handler.stream import StreamSink
from rfnry_chat_server.handler.types import HandlerCallable
from rfnry_chat_server.store.protocol import ChatStore


class PublishEventCallable(Protocol):
    async def __call__(self, event: Event, *, thread: Thread | None = None) -> Event: ...


PublishThreadUpdatedCallable = Callable[[Thread], Awaitable[None]]
HandlerResolver = Callable[[str], HandlerCallable | None]
StreamSinkFactory = Callable[[Thread], StreamSink]


class RunExecutor:
    def __init__(
        self,
        store: ChatStore,
        on_analytics: OnAnalyticsCallback | None = None,
        run_timeout_seconds: int = 120,
        publish_event: PublishEventCallable | None = None,
        publish_thread_updated: PublishThreadUpdatedCallable | None = None,
        handler_resolver: HandlerResolver | None = None,
        stream_sink_factory: StreamSinkFactory | None = None,
    ) -> None:
        self._store = store
        self._on_analytics = on_analytics
        self._run_timeout_seconds = run_timeout_seconds
        if publish_event is None:

            async def _default_publish(event: Event, *, thread: Thread | None = None) -> Event:
                return await store.append_event(event)

            self._publish_event: PublishEventCallable = _default_publish
        else:
            self._publish_event = publish_event
        self._publish_thread_updated = publish_thread_updated
        self._handler_resolver = handler_resolver
        self._stream_sink_factory = stream_sink_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._chain_depths: dict[str, int] = {}

    def chain_depth_for(self, run_id: str) -> int:
        return self._chain_depths.get(run_id, 0)

    async def invoke_from_handler(
        self,
        thread: Thread,
        triggered_by: Identity,
        assistant_id: str,
    ) -> Run:
        if self._handler_resolver is None:
            raise RuntimeError("handler_resolver not configured on RunExecutor")
        handler = self._handler_resolver(assistant_id)
        if handler is None:
            raise ValueError(f"assistant not registered: {assistant_id}")
        members = await self._store.list_members(thread.id)
        member = next((m for m in members if m.identity_id == assistant_id), None)
        if member is None or not isinstance(member.identity, AssistantIdentity):
            raise ValueError(f"assistant not a member of this thread: {assistant_id}")
        return await self.execute(
            thread=thread,
            assistant=member.identity,
            triggered_by=triggered_by,
            handler=handler,
        )

    async def execute(
        self,
        thread: Thread,
        assistant: AssistantIdentity,
        triggered_by: Identity,
        handler: HandlerCallable,
        idempotency_key: str | None = None,
        *,
        chain_depth: int = 0,
    ) -> Run:
        if idempotency_key:
            existing = await self._store.find_run_by_idempotency_key(thread.id, idempotency_key)
            if existing:
                return existing

        existing_active = await self._store.find_active_run(thread.id, actor_id=assistant.id)
        if existing_active:
            return existing_active

        run = Run(
            id=f"run_{secrets.token_hex(8)}",
            thread_id=thread.id,
            actor=assistant,
            triggered_by=triggered_by,
            status="pending",
            started_at=datetime.now(UTC),
            idempotency_key=idempotency_key,
        )
        try:
            run = await self._store.create_run(run)
        except asyncpg.exceptions.UniqueViolationError:
            existing_active = await self._store.find_active_run(thread.id, actor_id=assistant.id)
            if existing_active:
                return existing_active
            if idempotency_key:
                existing = await self._store.find_run_by_idempotency_key(thread.id, idempotency_key)
                if existing:
                    return existing
            raise

        self._chain_depths[run.id] = chain_depth
        task = asyncio.create_task(self._drive(run, thread, assistant, handler))
        self._tasks[run.id] = task
        return run

    async def cancel(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()

    async def await_run(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is None:
            return
        try:
            await task
        except (Exception, asyncio.CancelledError):
            pass

    async def _drive(
        self,
        run: Run,
        thread: Thread,
        assistant: AssistantIdentity,
        handler: HandlerCallable,
    ) -> None:
        analytics = AssistantAnalytics(
            on_analytics=self._on_analytics,
            thread_id=thread.id,
            run_id=run.id,
            assistant_id=assistant.id,
        )
        try:
            run = await self._store.update_run_status(run.id, "running")
            await self._publish_event(_run_started(run, thread, assistant), thread=thread)

            async def _chain_invoke(assistant_id: str) -> Run:
                return await self.invoke_from_handler(thread, assistant, assistant_id)

            async def _update_thread_helper(current_thread: Thread, patch: ThreadPatch) -> Thread:
                # Match the REST patch-thread behavior: write the patch,
                # publish a tenant_changed event if tenant changed, then
                # broadcast the updated thread. No authorize check —
                # handlers are trusted server-side code.
                updated = await self._store.update_thread(current_thread.id, patch)
                if patch.tenant is not None and patch.tenant != current_thread.tenant:
                    tenant_event = ThreadTenantChangedEvent.model_validate(
                        {
                            "id": f"evt_{secrets.token_hex(8)}",
                            "thread_id": current_thread.id,
                            "author": assistant.model_dump(mode="json"),
                            "created_at": datetime.now(UTC),
                            "type": "thread.tenant_changed",
                            "from": current_thread.tenant,
                            "to": patch.tenant,
                        }
                    )
                    await self._publish_event(tenant_event, thread=updated)
                if self._publish_thread_updated is not None:
                    await self._publish_thread_updated(updated)
                return updated

            ctx = HandlerContext(
                store=self._store,
                thread=thread,
                run=run,
                assistant=assistant,
                analytics=analytics,
                invoke_assistant=_chain_invoke,
                update_thread=_update_thread_helper,
            )
            stream_sink = self._stream_sink_factory(thread) if self._stream_sink_factory is not None else None
            send = HandlerSend(
                thread_id=thread.id,
                run_id=run.id,
                author=assistant,
                stream_sink=stream_sink,
            )

            async def _consume() -> None:
                async for event in handler(ctx, send):
                    await self._publish_event(event, thread=thread)

            await asyncio.wait_for(_consume(), timeout=self._run_timeout_seconds)

            await self._store.update_run_status(run.id, "completed")
            await self._publish_event(_run_completed(run, thread, assistant), thread=thread)
        except asyncio.CancelledError:
            await self._store.update_run_status(run.id, "cancelled")
            await self._publish_event(_run_cancelled(run, thread, assistant), thread=thread)
            raise
        except TimeoutError:
            err = RunError(
                code="timeout",
                message=f"run exceeded {self._run_timeout_seconds}s",
            )
            await self._store.update_run_status(run.id, "failed", error=err)
            await self._publish_event(_run_failed(run, thread, assistant, err), thread=thread)
        except Exception as exc:
            err = RunError(code="handler_error", message=str(exc))
            await self._store.update_run_status(run.id, "failed", error=err)
            await self._publish_event(_run_failed(run, thread, assistant, err), thread=thread)
            raise
        finally:
            await analytics.flush()
            self._tasks.pop(run.id, None)
            self._chain_depths.pop(run.id, None)


def _evt_id() -> str:
    return f"evt_{secrets.token_hex(8)}"


def _run_started(run: Run, thread: Thread, assistant: AssistantIdentity) -> RunStartedEvent:
    return RunStartedEvent(
        id=_evt_id(),
        thread_id=thread.id,
        run_id=run.id,
        author=assistant,
        created_at=datetime.now(UTC),
    )


def _run_completed(run: Run, thread: Thread, assistant: AssistantIdentity) -> RunCompletedEvent:
    return RunCompletedEvent(
        id=_evt_id(),
        thread_id=thread.id,
        run_id=run.id,
        author=assistant,
        created_at=datetime.now(UTC),
    )


def _run_cancelled(run: Run, thread: Thread, assistant: AssistantIdentity) -> RunCancelledEvent:
    return RunCancelledEvent(
        id=_evt_id(),
        thread_id=thread.id,
        run_id=run.id,
        author=assistant,
        created_at=datetime.now(UTC),
    )


def _run_failed(
    run: Run,
    thread: Thread,
    assistant: AssistantIdentity,
    err: RunError,
) -> RunFailedEvent:
    return RunFailedEvent.model_validate(
        {
            "id": _evt_id(),
            "thread_id": thread.id,
            "run_id": run.id,
            "author": assistant.model_dump(mode="json"),
            "created_at": datetime.now(UTC),
            "type": "run.failed",
            "error": {"code": err.code, "message": err.message},
        }
    )
