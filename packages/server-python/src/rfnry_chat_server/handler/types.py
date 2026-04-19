from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rfnry_chat_server.handler.context import HandlerContext
    from rfnry_chat_server.handler.send import HandlerSend
    from rfnry_chat_server.protocol.event import Event

HandlerCallable = Callable[
    ["HandlerContext", "HandlerSend"],
    AsyncGenerator["Event", None],
]
