from __future__ import annotations

from typing import Protocol

from rfnry_chat_protocol import (
    Event,
    Identity,
    PresenceJoinedFrame,
    PresenceLeftFrame,
    Run,
    StreamDeltaFrame,
    StreamEndFrame,
    StreamStartFrame,
    Thread,
    ThreadInvitedFrame,
)


class Broadcaster(Protocol):
    async def broadcast_event(self, event: Event, *, namespace: str | None = None) -> None: ...
    async def broadcast_thread_updated(self, thread: Thread, *, namespace: str | None = None) -> None: ...
    async def broadcast_members_updated(
        self,
        thread_id: str,
        members: list[Identity],
        *,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_run_updated(self, run: Run, *, namespace: str | None = None) -> None: ...
    async def broadcast_thread_invited(
        self,
        frame: ThreadInvitedFrame,
        *,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_presence_joined(
        self,
        frame: PresenceJoinedFrame,
        *,
        tenant_path: str,
        skip_sid: str | None = None,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_presence_left(
        self,
        frame: PresenceLeftFrame,
        *,
        tenant_path: str,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_thread_cleared(
        self,
        thread_id: str,
        *,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_thread_created(
        self,
        thread: Thread,
        *,
        room: str,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_thread_deleted(
        self,
        thread_id: str,
        tenant: dict[str, str],
        *,
        room: str,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_stream_start(
        self,
        frame: StreamStartFrame,
        *,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_stream_delta(
        self,
        frame: StreamDeltaFrame,
        *,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_stream_end(
        self,
        frame: StreamEndFrame,
        *,
        namespace: str | None = None,
    ) -> None: ...
