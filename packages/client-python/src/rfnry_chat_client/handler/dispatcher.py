from __future__ import annotations

import asyncio
import contextvars
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from rfnry_chat_protocol import (
    AssistantIdentity,
    Event,
    Identity,
    RunError,
    SystemIdentity,
    UserIdentity,
    parse_event,
)

from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.handler.types import HandlerCallable
from rfnry_chat_client.send import Send
from rfnry_chat_client.telemetry import TelemetryRow

if TYPE_CHECKING:
    from rfnry_chat_client.client import ChatClient

MAX_HANDLER_CHAIN_DEPTH = 8

_chain_depth: contextvars.ContextVar[int] = contextvars.ContextVar("rfnry_chat_client_handler_chain_depth", default=0)


IdempotencyKeyFn = Callable[[Event], "str | None"]


@dataclass(frozen=True)
class _Registration:
    event_type: str
    handler: HandlerCallable
    all_events: bool
    tool_name: str | None
    lazy_run: bool
    idempotency_key: IdempotencyKeyFn | None


_RECENT_EVENT_LIMIT = 256


@dataclass
class _ClientRunAccumulator:
    started_monotonic: float = field(default_factory=time.monotonic)
    events_emitted: int = 0
    tool_calls: int = 0
    tool_errors: int = 0


def _scope_leaf_for_identity(identity: Identity) -> str:
    tenant = identity.metadata.get("tenant", {}) if hasattr(identity, "metadata") else {}
    if not isinstance(tenant, dict):
        return "default"
    parts = [str(v) for v in tenant.values() if isinstance(v, str)]
    return "/".join(parts) if parts else "default"


def _actor_kind_for(identity: Identity) -> str:
    if isinstance(identity, AssistantIdentity):
        return "assistant"
    if isinstance(identity, SystemIdentity):
        return "system"
    if isinstance(identity, UserIdentity):
        return "user"
    return "user"


class HandlerDispatcher:
    def __init__(self, *, identity: Identity, client: ChatClient) -> None:
        self._identity = identity
        self._client = client
        self._registrations: list[_Registration] = []
        self._recent_event_ids: dict[str, bool] = {}

    def register(
        self,
        event_type: str,
        handler: HandlerCallable,
        *,
        all_events: bool = False,
        tool_name: str | None = None,
        lazy_run: bool = False,
        idempotency_key: IdempotencyKeyFn | None = None,
    ) -> None:
        self._registrations.append(
            _Registration(
                event_type=event_type,
                handler=handler,
                all_events=all_events,
                tool_name=tool_name,
                lazy_run=lazy_run,
                idempotency_key=idempotency_key,
            )
        )

    async def feed(self, raw: dict[str, Any]) -> None:
        await self.feed_event(parse_event(raw))

    async def feed_event(self, event: Event) -> None:
        if event.id in self._recent_event_ids:
            return
        self._recent_event_ids[event.id] = True
        if len(self._recent_event_ids) > _RECENT_EVENT_LIMIT:
            oldest = next(iter(self._recent_event_ids))
            del self._recent_event_ids[oldest]

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
            key = reg.idempotency_key(event) if reg.idempotency_key is not None else None
            await self._run_emitter(
                reg.handler,
                event,
                lazy_run=reg.lazy_run,
                idempotency_key=key,
            )
            return
        await self._run_observer(reg.handler, event)

    async def _run_emitter(
        self,
        handler: HandlerCallable,
        event: Event,
        *,
        lazy_run: bool,
        idempotency_key: str | None,
    ) -> None:
        began_run_id: str | None = None
        accum = _ClientRunAccumulator()

        async def _start_run() -> str:
            nonlocal began_run_id
            if began_run_id is not None:
                return began_run_id
            reply = await self._client.socket.begin_run(
                event.thread_id,
                triggered_by_event_id=event.id,
                idempotency_key=idempotency_key,
            )
            began_run_id = reply["run_id"]
            return began_run_id

        ctx = HandlerContext(event=event, identity=self._identity, client=self._client)
        send = Send(
            thread_id=event.thread_id,
            author=self._identity,
            run_id=None,
            client=self._client,
            run_starter=_start_run,
            stream_error_code="handler_error",
        )

        if not lazy_run:
            run_id = await _start_run()
            send.set_run_id(run_id)

        try:
            async for emitted in handler(ctx, send):  # type: ignore[union-attr]
                updates: dict[str, Any] = {}
                if began_run_id is None:
                    run_id = await _start_run()
                    send.set_run_id(run_id)
                    if emitted.run_id is None:
                        updates["run_id"] = run_id
                elif emitted.run_id is None:
                    updates["run_id"] = began_run_id

                updates["created_at"] = datetime.now(UTC)
                emitted = emitted.model_copy(update=updates)
                await self._client.emit_event(emitted)
                accum.events_emitted += 1
                if emitted.type == "tool.call":
                    accum.tool_calls += 1
                elif emitted.type == "tool.result":
                    tool = getattr(emitted, "tool", None)
                    if tool is not None and getattr(tool, "error", None) is not None:
                        accum.tool_errors += 1
        except Exception as exc:
            await self._client.observability.emit(
                "handler.error",
                level="error",
                thread_id=event.thread_id,
                run_id=began_run_id,
                worker_id=self._identity.id,
                context={"event_type": event.type, "event_id": event.id},
                error=exc,
            )
            if began_run_id is not None:
                await self._client.socket.end_run(
                    began_run_id,
                    error={"code": "handler_error", "message": str(exc)},
                )
                row = self._build_telemetry_row(
                    began_run_id,
                    event,
                    accum,
                    "failed",
                    error_code="handler_error",
                    error_message=str(exc),
                )
                await self._client.telemetry.write(row)
            raise
        if began_run_id is not None:
            await self._client.socket.end_run(began_run_id)
            row = self._build_telemetry_row(
                began_run_id,
                event,
                accum,
                "completed",
                error_code=None,
                error_message=None,
            )
            await self._client.telemetry.write(row)

    def _build_telemetry_row(
        self,
        run_id: str,
        event: Event,
        accum: _ClientRunAccumulator,
        status: str,
        *,
        error_code: str | None,
        error_message: str | None,
    ) -> TelemetryRow:
        duration_ms = int((time.monotonic() - accum.started_monotonic) * 1000)
        return TelemetryRow(
            at=datetime.now(UTC),
            scope_leaf=_scope_leaf_for_identity(self._identity),
            thread_id=event.thread_id,
            run_id=run_id,
            actor_kind=_actor_kind_for(self._identity),  # type: ignore[arg-type]
            actor_id=self._identity.id,
            worker_id=self._identity.id,
            triggered_by_id=event.author.id,
            idempotency_key=None,
            status=status,  # type: ignore[arg-type]
            error_code=error_code,
            error_message=error_message,
            duration_ms=duration_ms,
            events_emitted=accum.events_emitted,
            tool_calls=accum.tool_calls,
            tool_errors=accum.tool_errors,
            stream_deltas=0,
        )

    async def _run_observer(self, handler: HandlerCallable, event: Event) -> None:
        ctx = HandlerContext(event=event, identity=self._identity, client=self._client)
        send = Send(
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


__all__ = ["HandlerDispatcher", "HandlerCallable", "MAX_HANDLER_CHAIN_DEPTH", "RunError"]
