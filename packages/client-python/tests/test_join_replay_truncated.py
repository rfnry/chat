from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.transport.socket import SocketTransport


def _make_client(sio: FakeSioClient) -> ChatClient:
    me = AssistantIdentity(id="a_me", name="Me")
    return ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )


def _replayed_event(event_id: str) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": event_id,
        "thread_id": "t_1",
        "run_id": None,
        "author": {"role": "user", "id": "u_1", "name": "U", "metadata": {}},
        "created_at": now,
        "metadata": {},
        "client_id": None,
        "recipients": None,
        "type": "message",
        "content": [{"type": "text", "text": event_id}],
    }


@pytest.mark.asyncio
async def test_join_thread_returns_replay_truncated_true() -> None:
    sio = FakeSioClient()
    sio.ack_replies["thread:join"] = {
        "thread_id": "t_1",
        "replayed": [_replayed_event("evt_1")],
        "replay_truncated": True,
    }
    client = _make_client(sio)
    await client.connect()

    result = await client.join_thread("t_1")
    assert result["replay_truncated"] is True
    assert len(result["replayed"]) == 1
    assert result["replayed"][0].id == "evt_1"


@pytest.mark.asyncio
async def test_join_thread_returns_replay_truncated_false() -> None:
    sio = FakeSioClient()
    sio.ack_replies["thread:join"] = {
        "thread_id": "t_1",
        "replayed": [],
        "replay_truncated": False,
    }
    client = _make_client(sio)
    await client.connect()

    result = await client.join_thread("t_1")
    assert result["replay_truncated"] is False
    assert result["replayed"] == []
