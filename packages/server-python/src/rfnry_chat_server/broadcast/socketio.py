from __future__ import annotations

import socketio
from rfnry_chat_protocol import (
    Event,
    Identity,
    Run,
    StreamDeltaFrame,
    StreamEndFrame,
    StreamStartFrame,
    Thread,
    ThreadInvitedFrame,
)


def _thread_room(thread_id: str) -> str:
    return f"thread:{thread_id}"


def _inbox_room(identity_id: str) -> str:
    return f"inbox:{identity_id}"


class SocketIOBroadcaster:
    def __init__(self, sio: socketio.AsyncServer) -> None:
        self._sio = sio

    async def broadcast_event(self, event: Event, *, namespace: str | None = None) -> None:
        await self._sio.emit(
            "event",
            event.model_dump(mode="json", by_alias=True),
            room=_thread_room(event.thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_thread_updated(self, thread: Thread, *, namespace: str | None = None) -> None:
        await self._sio.emit(
            "thread:updated",
            thread.model_dump(mode="json", by_alias=True),
            room=_thread_room(thread.id),
            namespace=namespace or "/",
        )

    async def broadcast_members_updated(
        self,
        thread_id: str,
        members: list[Identity],
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "members:updated",
            {
                "thread_id": thread_id,
                "members": [m.model_dump(mode="json") for m in members],
            },
            room=_thread_room(thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_run_updated(self, run: Run, *, namespace: str | None = None) -> None:
        await self._sio.emit(
            "run:updated",
            run.model_dump(mode="json", by_alias=True),
            room=_thread_room(run.thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_thread_invited(
        self,
        frame: ThreadInvitedFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "thread:invited",
            frame.model_dump(mode="json", by_alias=True),
            room=_inbox_room(frame.added_member.id),
            namespace=namespace or "/",
        )

    async def broadcast_thread_cleared(
        self,
        thread_id: str,
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "thread:cleared",
            {"thread_id": thread_id},
            room=_thread_room(thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_thread_created_to_sids(
        self,
        thread: Thread,
        targets: list[tuple[str, str]],
    ) -> None:
        payload = thread.model_dump(mode="json", by_alias=True)
        for sid, ns in targets:
            await self._sio.emit(
                "thread:created",
                payload,
                to=sid,
                namespace=ns or "/",
            )

    async def broadcast_thread_deleted_to_sids(
        self,
        thread_id: str,
        targets: list[tuple[str, str]],
    ) -> None:
        payload = {"thread_id": thread_id}
        for sid, ns in targets:
            await self._sio.emit(
                "thread:deleted",
                payload,
                to=sid,
                namespace=ns or "/",
            )

    async def broadcast_stream_start(
        self,
        frame: StreamStartFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "stream:start",
            frame.model_dump(mode="json", by_alias=True),
            room=_thread_room(frame.thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_stream_delta(
        self,
        frame: StreamDeltaFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "stream:delta",
            frame.model_dump(mode="json", by_alias=True),
            room=_thread_room(frame.thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_stream_end(
        self,
        frame: StreamEndFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "stream:end",
            frame.model_dump(mode="json", by_alias=True),
            room=_thread_room(frame.thread_id),
            namespace=namespace or "/",
        )
