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
    """Dispatches `thread:invited` frames to registered `@on_invited` handlers.

    Contract: when `auto_join=True` (the default), the dispatcher awaits
    `client.join_thread(frame.thread.id)` BEFORE any user handler runs. This
    lets handlers assume their socket is already subscribed to the thread
    room, so they can e.g. `send_message` into that thread without racing.
    """

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
            # Auto-join is best-effort. Transport / HTTP failures are logged
            # and swallowed so user handlers still fire — but programmer
            # errors (AttributeError, TypeError, etc.) propagate normally.
            try:
                await self._client.join_thread(frame.thread.id)
            except (SocketTransportError, ChatHttpError) as exc:
                _log.debug("auto-join failed for thread %s: %s", frame.thread.id, exc)
        results = [handler(frame) for handler in self._handlers]
        awaitables = [r for r in results if inspect.isawaitable(r)]
        if awaitables:
            await asyncio.gather(*awaitables)
