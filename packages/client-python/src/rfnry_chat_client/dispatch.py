from __future__ import annotations

import asyncio
import contextvars
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rfnry_chat_protocol import Event, Identity, RunError, parse_event

from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.handler.send import HandlerSend
from rfnry_chat_client.handler.types import HandlerCallable

if TYPE_CHECKING:
    from rfnry_chat_client.client import ChatClient

MAX_HANDLER_CHAIN_DEPTH = 8

_chain_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "rfnry_chat_client_handler_chain_depth", default=0
)


@dataclass(frozen=True)
class _Registration:
    event_type: str
    handler: HandlerCallable
    all_events: bool
    tool_name: str | None
    in_run: bool


class Dispatcher:
    def __init__(self, *, identity: Identity, client: ChatClient) -> None:
        self._identity = identity
        self._client = client
        self._registrations: list[_Registration] = []

    def register(
        self,
        event_type: str,
        handler: HandlerCallable,
        *,
        all_events: bool = False,
        tool_name: str | None = None,
        in_run: bool = False,
    ) -> None:
        self._registrations.append(
            _Registration(
                event_type=event_type,
                handler=handler,
                all_events=all_events,
                tool_name=tool_name,
                in_run=in_run,
            )
        )

    async def feed(self, raw: dict[str, Any]) -> None:
        event = parse_event(raw)
        if _chain_depth.get() >= MAX_HANDLER_CHAIN_DEPTH:
            return
        matches: list[_Registration] = []
        for reg in self._registrations:
            if not _matches_type(reg, event):
                continue
            if not reg.all_events and not _passes_default_filters(event, self._identity.id):
                continue
            matches.append(reg)
        if not matches:
            return
        token = _chain_depth.set(_chain_depth.get() + 1)
        try:
            await asyncio.gather(*(self._run_one(reg, event) for reg in matches))
        finally:
            _chain_depth.reset(token)

    async def _run_one(self, reg: _Registration, event: Event) -> None:
        run_id: str | None = None
        if reg.in_run:
            begin_reply = await self._client.socket.begin_run(
                event.thread_id,
                triggered_by_event_id=event.id,
            )
            run_id = begin_reply["run_id"]

        ctx = HandlerContext(event=event, identity=self._identity, client=self._client)
        send = HandlerSend(thread_id=event.thread_id, author=self._identity, run_id=run_id)

        try:
            await self._invoke(reg.handler, ctx, send)
        except Exception as exc:
            if run_id is not None:
                await self._client.socket.end_run(
                    run_id,
                    error={"code": "handler_error", "message": str(exc)},
                )
            raise

        if run_id is not None:
            await self._client.socket.end_run(run_id)

    async def _invoke(
        self, handler: HandlerCallable, ctx: HandlerContext, send: HandlerSend
    ) -> None:
        if inspect.isasyncgenfunction(handler):
            async for emitted in handler(ctx, send):
                await self._client.emit_event(emitted)
            return
        result: Any = handler(ctx, send)
        if inspect.isawaitable(result):
            await result


def _matches_type(reg: _Registration, event: Event) -> bool:
    if reg.event_type == "*":
        return True
    if reg.event_type != event.type:
        return False
    if reg.tool_name is not None and event.type == "tool.call":
        return event.tool.name == reg.tool_name
    return True


def _passes_default_filters(event: Event, self_id: str) -> bool:
    if event.author.id == self_id:
        return False
    if event.recipients is not None and self_id not in event.recipients:
        return False
    return True


__all__ = ["Dispatcher", "HandlerCallable", "MAX_HANDLER_CHAIN_DEPTH", "RunError"]
