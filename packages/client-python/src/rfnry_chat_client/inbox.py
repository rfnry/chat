from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from rfnry_chat_protocol import ThreadInvitedFrame

if TYPE_CHECKING:
    from rfnry_chat_client.client import ChatClient

InviteHandler = Callable[[ThreadInvitedFrame], Awaitable[None] | None]


class InboxDispatcher:
    def __init__(self, *, client: ChatClient, auto_join: bool) -> None:
        self._client = client
        self._auto_join = auto_join
        self._handlers: list[InviteHandler] = []

    def register(self, handler: InviteHandler) -> InviteHandler:
        self._handlers.append(handler)
        return handler

    async def feed(self, raw: dict[str, Any]) -> None:
        frame = ThreadInvitedFrame.model_validate(raw)
        if self._auto_join:
            try:
                await self._client.join_thread(frame.thread.id)
            except Exception:
                # Auto-join is best-effort; user handlers still fire.
                pass
        for handler in self._handlers:
            result: Any = handler(frame)
            if inspect.isawaitable(result):
                await result
