from __future__ import annotations

from typing import Protocol

from rfnry_chat_protocol import Event, Identity, Run, StreamDeltaFrame, StreamEndFrame, StreamStartFrame, Thread


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
