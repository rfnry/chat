from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rfnry_chat_server.tools.runner import ToolCallContext

ToolCallHandler = Callable[["ToolCallContext"], Awaitable[Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ToolCallHandler] = {}

    def register(self, name: str, handler: ToolCallHandler) -> None:
        if name in self._handlers:
            raise ValueError(f"tool handler already registered: {name}")
        self._handlers[name] = handler

    def decorator(self, name: str) -> Callable[[ToolCallHandler], ToolCallHandler]:
        def wrap(handler: ToolCallHandler) -> ToolCallHandler:
            self.register(name, handler)
            return handler

        return wrap

    def get(self, name: str) -> ToolCallHandler | None:
        return self._handlers.get(name)
