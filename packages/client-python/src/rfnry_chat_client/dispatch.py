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

_chain_depth: contextvars.ContextVar[int] = contextvars.ContextVar("rfnry_chat_client_handler_chain_depth", default=0)


@dataclass(frozen=True)
class _Registration:
    event_type: str
    handler: HandlerCallable
    all_events: bool
    tool_name: str | None


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
    ) -> None:
        self._registrations.append(
            _Registration(
                event_type=event_type,
                handler=handler,
                all_events=all_events,
                tool_name=tool_name,
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
        if inspect.isasyncgenfunction(reg.handler):
            await self._run_emitter(reg.handler, event)
            return
        await self._run_observer(reg.handler, event)

    async def _run_emitter(self, handler: HandlerCallable, event: Event) -> None:
        # Lazy run creation. Previously we called begin_run unconditionally
        # on every dispatch — so a handler that early-returned (e.g. a role
        # filter guard `if event.author.role != "user": return`) still
        # produced an empty run and one run.started + run.completed frame.
        # In a multi-agent channel that fans out to N-1 other agents, this
        # caused N phantom runs per user message.
        #
        # Now: build a `run_starter` closure. We only call begin_run on the
        # handler's first yield (or first stream open). Handlers that yield
        # nothing skip begin_run AND end_run entirely.
        began_run_id: str | None = None

        async def _start_run() -> str:
            nonlocal began_run_id
            if began_run_id is not None:
                return began_run_id
            reply = await self._client.socket.begin_run(
                event.thread_id,
                triggered_by_event_id=event.id,
            )
            began_run_id = reply["run_id"]
            return began_run_id

        ctx = HandlerContext(event=event, identity=self._identity, client=self._client)
        send = HandlerSend(
            thread_id=event.thread_id,
            author=self._identity,
            run_id=None,
            client=self._client,
            run_starter=_start_run,
        )

        try:
            async for emitted in handler(ctx, send):  # type: ignore[union-attr]
                # Trigger begin_run on the first emission and stamp the
                # run_id onto the emitted event. Events are frozen Pydantic
                # models, so we use model_copy to produce a patched copy.
                if began_run_id is None:
                    run_id = await _start_run()
                    send.set_run_id(run_id)
                    if emitted.run_id is None:
                        emitted = emitted.model_copy(update={"run_id": run_id})
                await self._client.emit_event(emitted)
        except Exception as exc:
            if began_run_id is not None:
                await self._client.socket.end_run(
                    began_run_id,
                    error={"code": "handler_error", "message": str(exc)},
                )
            raise
        if began_run_id is not None:
            await self._client.socket.end_run(began_run_id)

    async def _run_observer(self, handler: HandlerCallable, event: Event) -> None:
        ctx = HandlerContext(event=event, identity=self._identity, client=self._client)
        send = HandlerSend(
            thread_id=event.thread_id,
            author=self._identity,
            run_id=None,
            client=self._client,
        )
        result: Any = handler(ctx, send)  # type: ignore[call-overload]
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
