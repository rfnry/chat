from __future__ import annotations

import contextvars
import inspect
from typing import TYPE_CHECKING, Any

from rfnry_chat_protocol import Event, RunError, SystemIdentity, Thread

from rfnry_chat_server.handler.context import HandlerContext
from rfnry_chat_server.handler.registry import HandlerRegistration, HandlerRegistry
from rfnry_chat_server.handler.types import HandlerCallable
from rfnry_chat_server.send import Send

if TYPE_CHECKING:
    from rfnry_chat_server.server import ChatServer

MAX_HANDLER_CHAIN_DEPTH = 8

_chain_depth: contextvars.ContextVar[int] = contextvars.ContextVar("rfnry_chat_server_handler_chain_depth", default=0)


class HandlerDispatcher:
    def __init__(
        self,
        *,
        server: ChatServer,
        registry: HandlerRegistry,
        system_identity: SystemIdentity,
    ) -> None:
        self._server = server
        self._registry = registry
        self._system = system_identity

    async def dispatch(self, event: Event, thread: Thread) -> None:
        if _chain_depth.get() >= MAX_HANDLER_CHAIN_DEPTH:
            return
        if event.author.id == self._system.id:
            return
        matches = self._registry.matches(event)
        if not matches:
            return
        token = _chain_depth.set(_chain_depth.get() + 1)
        try:
            for entry in matches:
                await self._run_one(entry, event, thread)
        finally:
            _chain_depth.reset(token)

    async def _run_one(self, entry: HandlerRegistration, event: Event, thread: Thread) -> None:
        if inspect.isasyncgenfunction(entry.handler):
            await self._run_emitter(
                entry.handler,
                event,
                thread,
                lazy_run=entry.lazy_run,
                idempotency_key=entry.idempotency_key(event) if entry.idempotency_key else None,
            )
            return
        await self._run_observer(entry.handler, event, thread)

    async def _run_emitter(
        self,
        handler: HandlerCallable,
        event: Event,
        thread: Thread,
        *,
        lazy_run: bool,
        idempotency_key: str | None,
    ) -> None:
        began_run_id: str | None = None

        async def _start_run() -> str:
            nonlocal began_run_id
            if began_run_id is not None:
                return began_run_id
            run = await self._server.begin_run(
                thread=thread,
                actor=self._system,
                triggered_by=event.author,
                idempotency_key=idempotency_key,
            )
            began_run_id = run.id
            return began_run_id

        ctx = HandlerContext(event=event, thread=thread, store=self._server.store, server=self._server)
        send = Send(
            thread_id=thread.id,
            author=self._system,
            run_id=None,
            run_starter=_start_run,
            server=self._server,
            thread=thread,
        )

        if not lazy_run:
            run_id = await _start_run()
            send.set_run_id(run_id)

        try:
            async for emitted in handler(ctx, send):  # type: ignore[union-attr]
                if began_run_id is None:
                    run_id = await _start_run()
                    send.set_run_id(run_id)
                    if emitted.run_id is None:
                        emitted = emitted.model_copy(update={"run_id": run_id})
                elif emitted.run_id is None:
                    emitted = emitted.model_copy(update={"run_id": began_run_id})
                await self._server.publish_event(emitted, thread=ctx.thread)
        except Exception as exc:
            await self._server.observability.log(
                "handler.error",
                level="error",
                thread_id=thread.id,
                run_id=began_run_id,
                worker_id=self._system.id,
                scope_leaf=self._server.scope_leaf_for_thread(thread),
                context={"event_type": event.type, "event_id": event.id},
                error=exc,
            )
            if began_run_id is not None:
                await self._server.end_run(
                    run_id=began_run_id,
                    error=RunError(code="handler_error", message=str(exc)),
                )
            raise
        if began_run_id is not None:
            await self._server.end_run(run_id=began_run_id, error=None)

    async def _run_observer(self, handler: HandlerCallable, event: Event, thread: Thread) -> None:
        ctx = HandlerContext(event=event, thread=thread, store=self._server.store, server=self._server)
        send = Send(thread_id=thread.id, author=self._system, run_id=None)
        result: Any = handler(ctx, send)  # type: ignore[call-overload]
        if inspect.isawaitable(result):
            await result
