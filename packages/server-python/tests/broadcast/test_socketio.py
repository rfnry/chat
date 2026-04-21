from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

from rfnry_chat_protocol import AssistantIdentity, Thread, ThreadInvitedFrame, UserIdentity

from rfnry_chat_server.broadcast.socketio import SocketIOBroadcaster


async def test_broadcast_thread_invited_emits_to_inbox_room() -> None:
    sio = AsyncMock()
    b = SocketIOBroadcaster(sio)
    now = datetime.now(UTC)
    frame = ThreadInvitedFrame(
        thread=Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now),
        added_member=UserIdentity(id="u_alice", name="Alice", metadata={}),
        added_by=AssistantIdentity(id="a_bot", name="Bot", metadata={}),
    )
    await b.broadcast_thread_invited(frame, namespace="/A")

    sio.emit.assert_awaited_once()
    args, kwargs = sio.emit.call_args
    assert args[0] == "thread:invited"
    payload: dict[str, Any] = args[1]
    assert payload["thread"]["id"] == "th_1"
    assert payload["added_member"]["id"] == "u_alice"
    assert payload["added_by"]["id"] == "a_bot"
    assert kwargs["room"] == "inbox:u_alice"
    assert kwargs["namespace"] == "/A"


async def test_broadcast_thread_invited_defaults_namespace_to_root() -> None:
    sio = AsyncMock()
    b = SocketIOBroadcaster(sio)
    now = datetime.now(UTC)
    frame = ThreadInvitedFrame(
        thread=Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now),
        added_member=UserIdentity(id="u_bob", name="Bob", metadata={}),
        added_by=AssistantIdentity(id="a_bot", name="Bot", metadata={}),
    )
    await b.broadcast_thread_invited(frame)
    _, kwargs = sio.emit.call_args
    assert kwargs["namespace"] == "/"
    assert kwargs["room"] == "inbox:u_bob"
