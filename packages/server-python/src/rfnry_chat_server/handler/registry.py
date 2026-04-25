from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rfnry_chat_protocol import Event

from rfnry_chat_server.handler.types import HandlerCallable


@dataclass(frozen=True)
class HandlerRegistration:
    event_type: str
    handler: HandlerCallable
    tool_name: str | None
    lazy_run: bool


class HandlerRegistry:
    def __init__(self) -> None:
        self._entries: list[HandlerRegistration] = []

    def register(
        self,
        event_type: str,
        handler: HandlerCallable,
        *,
        tool_name: str | None = None,
        lazy_run: bool = False,
    ) -> None:
        self._entries.append(
            HandlerRegistration(
                event_type=event_type,
                handler=handler,
                tool_name=tool_name,
                lazy_run=lazy_run,
            )
        )

    def matches(self, event: Event) -> list[HandlerRegistration]:
        out: list[HandlerRegistration] = []
        for entry in self._entries:
            if entry.event_type != "*" and entry.event_type != event.type:
                continue
            if entry.tool_name is not None:
                if event.type != "tool.call":
                    continue
                if event.tool.name != entry.tool_name:
                    continue
            out.append(entry)
        return out

    def decorator(
        self,
        event_type: str,
        *,
        tool: str | None = None,
        lazy_run: bool = False,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        def wrap(handler: HandlerCallable) -> HandlerCallable:
            self.register(event_type, handler, tool_name=tool, lazy_run=lazy_run)
            return handler

        return wrap
