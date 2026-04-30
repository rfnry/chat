from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from rfnry_chat_protocol import ThreadInvitedFrame

from rfnry_chat_client.errors import ChatHttpError
from rfnry_chat_client.transport.socket import SocketTransportError

if TYPE_CHECKING:
    from rfnry_chat_client.client import ChatClient

InviteHandler = Callable[[ThreadInvitedFrame], Awaitable[None] | None]

_log = logging.getLogger("rfnry_chat_client.inbox")


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
            except (SocketTransportError, ChatHttpError) as exc:
                _log.debug("auto-join failed for thread %s: %s", frame.thread.id, exc)
        results = [handler(frame) for handler in self._handlers]
        awaitables = [r for r in results if inspect.isawaitable(r)]
        if awaitables:
            await asyncio.gather(*awaitables)
