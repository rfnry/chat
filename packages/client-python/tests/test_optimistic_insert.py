from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity, Event, MessageEvent, TextPart

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.send import Send
from rfnry_chat_client.transport.socket import SocketTransport


def _ack_event(event_id: str = "evt_optim") -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "event": {
            "id": event_id,
            "thread_id": "t_1",
            "run_id": None,
            "author": {"role": "assistant", "id": "a_me", "name": "Me", "metadata": {}},
            "created_at": now,
            "metadata": {},
            "client_id": None,
            "recipients": None,
            "type": "message",
            "content": [{"type": "text", "text": "hi"}],
        }
    }


@pytest.mark.asyncio
async def test_send_message_dispatches_to_local_handlers() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    sio.ack_replies["message:send"] = _ack_event()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    received: list[Event] = []

    @client.on_message(all_events=True)
    async def capture(ctx: HandlerContext, _send: Send) -> None:
        received.append(ctx.event)

    await client.connect()
    event = await client.send_message("t_1", content=[TextPart(text="hi")])

    assert isinstance(event, MessageEvent)
    assert event.id == "evt_optim"
    assert len(received) == 1
    assert received[0].id == "evt_optim"


@pytest.mark.asyncio
async def test_dispatch_dedupes_when_broadcast_and_optimistic_collide() -> None:
    """If the broadcast also delivers the same event id (REST + socket race),
    the dispatcher's LRU drops the duplicate so handlers fire exactly once."""
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    sio.ack_replies["message:send"] = _ack_event(event_id="evt_dup")
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    received: list[Event] = []

    @client.on_message(all_events=True)
    async def capture(ctx: HandlerContext, _send: Send) -> None:
        received.append(ctx.event)

    await client.connect()

    await client.send_message("t_1", content=[TextPart(text="hi")])

    raw_handler = sio.handlers["event"]
    await raw_handler({
        "id": "evt_dup",
        "thread_id": "t_1",
        "run_id": None,
        "author": {"role": "assistant", "id": "a_me", "name": "Me", "metadata": {}},
        "created_at": datetime.now(UTC).isoformat(),
        "metadata": {},
        "client_id": None,
        "recipients": None,
        "type": "message",
        "content": [{"type": "text", "text": "hi"}],
    })

    assert [e.id for e in received] == ["evt_dup"]
