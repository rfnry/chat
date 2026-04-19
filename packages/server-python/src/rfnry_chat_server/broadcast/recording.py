from __future__ import annotations

from rfnry_chat_server.protocol.event import Event
from rfnry_chat_server.protocol.identity import Identity
from rfnry_chat_server.protocol.run import Run
from rfnry_chat_server.protocol.stream import StreamDeltaFrame, StreamEndFrame, StreamStartFrame
from rfnry_chat_server.protocol.thread import Thread


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.threads_updated: list[Thread] = []
        self.members_updated: list[tuple[str, list[Identity]]] = []
        self.runs_updated: list[Run] = []
        self.events_with_namespace: list[tuple[Event, str | None]] = []
        self.threads_updated_with_namespace: list[tuple[Thread, str | None]] = []
        self.members_updated_with_namespace: list[tuple[str, list[Identity], str | None]] = []
        self.runs_updated_with_namespace: list[tuple[Run, str | None]] = []
        self.stream_starts: list[StreamStartFrame] = []
        self.stream_deltas: list[StreamDeltaFrame] = []
        self.stream_ends: list[StreamEndFrame] = []

    async def broadcast_event(self, event: Event, *, namespace: str | None = None) -> None:
        self.events.append(event)
        self.events_with_namespace.append((event, namespace))

    async def broadcast_thread_updated(self, thread: Thread, *, namespace: str | None = None) -> None:
        self.threads_updated.append(thread)
        self.threads_updated_with_namespace.append((thread, namespace))

    async def broadcast_members_updated(
        self,
        thread_id: str,
        members: list[Identity],
        *,
        namespace: str | None = None,
    ) -> None:
        self.members_updated.append((thread_id, members))
        self.members_updated_with_namespace.append((thread_id, members, namespace))

    async def broadcast_run_updated(self, run: Run, *, namespace: str | None = None) -> None:
        self.runs_updated.append(run)
        self.runs_updated_with_namespace.append((run, namespace))

    async def broadcast_stream_start(
        self,
        frame: StreamStartFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        self.stream_starts.append(frame)

    async def broadcast_stream_delta(
        self,
        frame: StreamDeltaFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        self.stream_deltas.append(frame)

    async def broadcast_stream_end(
        self,
        frame: StreamEndFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        self.stream_ends.append(frame)
