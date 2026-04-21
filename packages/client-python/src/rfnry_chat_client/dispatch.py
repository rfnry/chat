from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from rfnry_chat_protocol import Event, Identity, parse_event

EventHandler = Callable[[Event], Awaitable[None]]


@dataclass(frozen=True)
class _Registration:
    event_type: str
    handler: EventHandler
    all_events: bool
    tool_name: str | None


class Dispatcher:
    def __init__(self, *, identity: Identity) -> None:
        self._identity = identity
        self._registrations: list[_Registration] = []

    def register(
        self,
        event_type: str,
        handler: EventHandler,
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
        matches: list[EventHandler] = []
        for reg in self._registrations:
            if not _matches_type(reg, event):
                continue
            if not reg.all_events and not _passes_default_filters(event, self._identity.id):
                continue
            matches.append(reg.handler)
        if not matches:
            return
        await asyncio.gather(*(handler(event) for handler in matches))


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
