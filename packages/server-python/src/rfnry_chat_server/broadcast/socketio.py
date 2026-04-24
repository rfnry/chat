from __future__ import annotations

import socketio
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

from rfnry_chat_server.namespace import derive_namespace_path


def _thread_room(thread_id: str) -> str:
    return f"thread:{thread_id}"


def _inbox_room(identity_id: str) -> str:
    return f"inbox:{identity_id}"


def tenant_path(tenant: dict[str, str], *, namespace_keys: list[str] | None) -> str:
    """Deterministic tenant-path string for a tenant scope. Single source of
    truth for the path used by tenant rooms, presence rooms, and REST tenant
    filtering — callers that need the path for multiple purposes should derive
    it once and reuse to avoid drift."""
    return derive_namespace_path(tenant, namespace_keys=namespace_keys)


def _tenant_room(tenant: dict[str, str], namespace_keys: list[str] | None) -> str:
    """Deterministic room name for a tenant scope. Reuses derive_namespace_path
    so the same logic that defines tenant scoping defines room membership."""
    return f"tenant:{tenant_path(tenant, namespace_keys=namespace_keys)}"


def _presence_room(tenant_path: str) -> str:
    """Room name for presence-scope broadcasts. Every socket that authenticates
    into a given tenant path enters this room; presence:joined / presence:left
    frames go here."""
    return f"presence:{tenant_path}"


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

    async def broadcast_presence_joined(
        self,
        frame: PresenceJoinedFrame,
        *,
        tenant_path: str,
        namespace: str,
        skip_sid: str | None = None,
    ) -> None:
        """Broadcast a presence:joined frame to the tenant's presence room.

        `skip_sid` is the joining socket itself — excluded so the newly-connected
        client doesn't receive its own "joined" event. Other sockets (same
        identity with multiple tabs + all other identities in the same tenant
        scope) receive it.

        `namespace` is required (not defaulted to "/") because under wildcard
        namespace mode, "/" is not a registered namespace and emitting there
        silently no-ops. Callers in the connect/disconnect handlers already have
        the concrete namespace in hand — pass it explicitly.
        """
        await self._sio.emit(
            "presence:joined",
            frame.model_dump(mode="json", by_alias=True),
            room=_presence_room(tenant_path),
            skip_sid=skip_sid,
            namespace=namespace,
        )

    async def broadcast_presence_left(
        self,
        frame: PresenceLeftFrame,
        *,
        tenant_path: str,
        namespace: str,
    ) -> None:
        """Broadcast a presence:left frame to the tenant's presence room.

        No skip_sid here: by the time we broadcast, the departing socket is
        already disconnected and no longer in any room.

        `namespace` is required for the same reason as broadcast_presence_joined.
        """
        await self._sio.emit(
            "presence:left",
            frame.model_dump(mode="json", by_alias=True),
            room=_presence_room(tenant_path),
            namespace=namespace,
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

    async def broadcast_thread_created(
        self,
        thread: Thread,
        *,
        room: str,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "thread:created",
            thread.model_dump(mode="json", by_alias=True),
            room=room,
            namespace=namespace or "/",
        )

    async def broadcast_thread_deleted(
        self,
        thread_id: str,
        tenant: dict[str, str],
        *,
        room: str,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "thread:deleted",
            {"thread_id": thread_id},
            room=room,
            namespace=namespace or "/",
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
