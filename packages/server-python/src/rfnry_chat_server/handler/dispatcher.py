from __future__ import annotations

import contextvars
import inspect
from typing import TYPE_CHECKING, Any

from rfnry_chat_protocol import Event, RunError, SystemIdentity, Thread

from rfnry_chat_server.handler.context import HandlerContext
from rfnry_chat_server.handler.registry import HandlerRegistration, HandlerRegistry
from rfnry_chat_server.handler.send import HandlerSend
from rfnry_chat_server.handler.types import HandlerCallable

if TYPE_CHECKING:
    from rfnry_chat_server.server.chat_server import ChatServer

MAX_HANDLER_CHAIN_DEPTH = 8

_chain_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "rfnry_chat_server_handler_chain_depth", default=0
)


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

    async def _run_one(
        self, entry: HandlerRegistration, event: Event, thread: Thread
    ) -> None:
        if entry.in_run:
            run = await self._server.begin_run(
                thread=thread,
                actor=self._system,
                triggered_by=event.author,
                idempotency_key=None,
            )
            ctx = HandlerContext(
                event=event, thread=thread, store=self._server.store, server=self._server
            )
            send = HandlerSend(thread_id=thread.id, author=self._system, run_id=run.id)
            try:
                await self._invoke(entry.handler, ctx, send)
            except Exception as exc:
                await self._server.end_run(
                    run_id=run.id,
                    error=RunError(code="handler_error", message=str(exc)),
                )
                raise
            await self._server.end_run(run_id=run.id, error=None)
            return

        ctx = HandlerContext(
            event=event, thread=thread, store=self._server.store, server=self._server
        )
        send = HandlerSend(thread_id=thread.id, author=self._system, run_id=None)
        await self._invoke(entry.handler, ctx, send)

    async def _invoke(
        self, handler: HandlerCallable, ctx: HandlerContext, send: HandlerSend
    ) -> None:
        if inspect.isasyncgenfunction(handler):
            async for emitted in handler(ctx, send):
                await self._server.publish_event(emitted, thread=ctx.thread)
            return
        result: Any = handler(ctx, send)
        if inspect.isawaitable(result):
            await result
