from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity, ThreadInvitedFrame

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.transport.socket import SocketTransport


def _invited_frame_dict() -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "thread": {
            "id": "th_1",
            "tenant": {},
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        },
        "added_member": {"role": "assistant", "id": "a_me", "name": "Me", "metadata": {}},
        "added_by": {"role": "user", "id": "u_alice", "name": "Alice", "metadata": {}},
    }


async def _noop_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={})


async def test_on_invited_fires_on_thread_invited_frame() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_noop_handler)),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
        auto_join_on_invite=False,
    )
    received: list[ThreadInvitedFrame] = []

    @client.on_invited()
    async def handle(frame: ThreadInvitedFrame) -> None:
        received.append(frame)

    await client.connect()
    raw = sio.handlers["thread:invited"]
    await raw(_invited_frame_dict())
    assert len(received) == 1
    assert received[0].thread.id == "th_1"
    assert received[0].added_member.id == "a_me"


async def test_default_auto_join_invokes_thread_join() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_noop_handler)),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    await client.connect()
    raw = sio.handlers["thread:invited"]
    await raw(_invited_frame_dict())
    # FakeSioClient records thread:join calls. Verify auto-join fired.
    joined = [c for c in sio.calls if c[0] == "thread:join"]
    assert len(joined) == 1
    assert joined[0][1]["thread_id"] == "th_1"
