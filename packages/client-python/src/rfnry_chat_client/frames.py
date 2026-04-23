from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from rfnry_chat_protocol import (
    Identity,
    PresenceJoinedFrame,
    PresenceLeftFrame,
    Run,
    Thread,
    parse_identity,
)

ThreadUpdatedHandler = Callable[[Thread], Awaitable[None] | None]
MembersUpdatedHandler = Callable[[str, list[Identity]], Awaitable[None] | None]
RunUpdatedHandler = Callable[[Run], Awaitable[None] | None]
PresenceJoinedHandler = Callable[[PresenceJoinedFrame], Awaitable[None] | None]
PresenceLeftHandler = Callable[[PresenceLeftFrame], Awaitable[None] | None]

_log = logging.getLogger("rfnry_chat_client.frames")


class FrameDispatcher:
    """Dispatches transient server broadcast frames (thread:updated,
    members:updated, run:updated, presence:joined, presence:left) to
    registered handlers.

    These frames are snapshots carried over Socket.IO room broadcasts; they
    are NOT persisted events. For persisted events (message, tool.call, etc.)
    use `@client.on(...)` which routes through `Dispatcher`. For the
    `thread:invited` frame use `@client.on_invited()` (routes through
    `InboxDispatcher`, which also handles auto-join semantics).
    """

    def __init__(self) -> None:
        self._thread_updated: list[ThreadUpdatedHandler] = []
        self._members_updated: list[MembersUpdatedHandler] = []
        self._run_updated: list[RunUpdatedHandler] = []
        self._presence_joined: list[PresenceJoinedHandler] = []
        self._presence_left: list[PresenceLeftHandler] = []

    def register_thread_updated(self, handler: ThreadUpdatedHandler) -> ThreadUpdatedHandler:
        self._thread_updated.append(handler)
        return handler

    def register_members_updated(self, handler: MembersUpdatedHandler) -> MembersUpdatedHandler:
        self._members_updated.append(handler)
        return handler

    def register_run_updated(self, handler: RunUpdatedHandler) -> RunUpdatedHandler:
        self._run_updated.append(handler)
        return handler

    def register_presence_joined(self, handler: PresenceJoinedHandler) -> PresenceJoinedHandler:
        self._presence_joined.append(handler)
        return handler

    def register_presence_left(self, handler: PresenceLeftHandler) -> PresenceLeftHandler:
        self._presence_left.append(handler)
        return handler

    async def feed_thread_updated(self, raw: dict[str, Any]) -> None:
        thread = Thread.model_validate(raw)
        results = [handler(thread) for handler in self._thread_updated]
        awaitables = [r for r in results if inspect.isawaitable(r)]
        if awaitables:
            await asyncio.gather(*awaitables)

    async def feed_members_updated(self, raw: dict[str, Any]) -> None:
        thread_id = str(raw.get("thread_id") or "")
        members_raw = raw.get("members") or []
        members = [parse_identity(m) for m in members_raw if isinstance(m, dict)]
        results = [handler(thread_id, members) for handler in self._members_updated]
        awaitables = [r for r in results if inspect.isawaitable(r)]
        if awaitables:
            await asyncio.gather(*awaitables)

    async def feed_run_updated(self, raw: dict[str, Any]) -> None:
        run = Run.model_validate(raw)
        results = [handler(run) for handler in self._run_updated]
        awaitables = [r for r in results if inspect.isawaitable(r)]
        if awaitables:
            await asyncio.gather(*awaitables)

    async def feed_presence_joined(self, raw: dict[str, Any]) -> None:
        frame = PresenceJoinedFrame.model_validate(raw)
        results = [handler(frame) for handler in self._presence_joined]
        awaitables = [r for r in results if inspect.isawaitable(r)]
        if awaitables:
            await asyncio.gather(*awaitables)

    async def feed_presence_left(self, raw: dict[str, Any]) -> None:
        frame = PresenceLeftFrame.model_validate(raw)
        results = [handler(frame) for handler in self._presence_left]
        awaitables = [r for r in results if inspect.isawaitable(r)]
        if awaitables:
            await asyncio.gather(*awaitables)
