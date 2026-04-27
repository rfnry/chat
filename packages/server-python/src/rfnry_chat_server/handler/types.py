from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rfnry_chat_protocol import Event

    from rfnry_chat_server.handler.context import HandlerContext
    from rfnry_chat_server.send import Send

HandlerCallable = (
    Callable[["HandlerContext", "Send"], Awaitable[None]]
    | Callable[["HandlerContext", "Send"], AsyncGenerator["Event", None]]
)
