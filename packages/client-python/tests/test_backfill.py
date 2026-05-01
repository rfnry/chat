from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.transport.socket import SocketTransport


def _event_dict(event_id: str, created_at: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "thread_id": "t_1",
        "run_id": None,
        "author": {"role": "user", "id": "u_1", "name": "U", "metadata": {}},
        "created_at": created_at,
        "metadata": {},
        "client_id": None,
        "recipients": None,
        "type": "message",
        "content": [{"type": "text", "text": event_id}],
    }


def _make_client(captured: list[tuple[str, dict[str, Any] | None]]) -> ChatClient:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()

    async def fake_handler(request: httpx.Request) -> httpx.Response:
        captured.append((str(request.url), dict(request.url.params)))
        return httpx.Response(200, json={"items": [_event_dict("evt_old", "2026-04-20T00:00:00Z")]})

    transport = httpx.MockTransport(fake_handler)
    return ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(transport=transport),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )


@pytest.mark.asyncio
async def test_backfill_sends_before_query_params() -> None:
    captured: list[tuple[str, dict[str, Any] | None]] = []
    client = _make_client(captured)

    events, has_more = await client.backfill(
        "t_1",
        before=("2026-04-21T00:00:00Z", "evt_anchor"),
        limit=50,
    )

    assert len(captured) == 1
    params = captured[0][1] or {}
    assert params["before_created_at"] == "2026-04-21T00:00:00Z"
    assert params["before_id"] == "evt_anchor"
    assert params["limit"] == "50"
    assert events[0].id == "evt_old"
    assert has_more is False


@pytest.mark.asyncio
async def test_backfill_has_more_true_when_full() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    items = [_event_dict(f"evt_{i}", f"2026-04-20T00:00:0{i % 10}Z") for i in range(50)]

    async def fake_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": items})

    transport = httpx.MockTransport(fake_handler)
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(transport=transport),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )

    events, has_more = await client.backfill(
        "t_1",
        before=("2026-04-21T00:00:00Z", "evt_anchor"),
        limit=50,
    )

    assert len(events) == 50
    assert has_more is True
    # Drop the unused datetime import warning
    _ = datetime.now(UTC)
