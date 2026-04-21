from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity, TextPart

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.handler.send import HandlerSend
from rfnry_chat_client.transport.socket import SocketTransport


def _message_event_dict(
    *, author_id: str = "u_other", recipients: list[str] | None = None
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": "evt_1",
        "thread_id": "t_1",
        "run_id": None,
        "author": {"role": "user", "id": author_id, "name": author_id, "metadata": {}},
        "created_at": now,
        "metadata": {},
        "client_id": None,
        "recipients": recipients,
        "type": "message",
        "content": [{"type": "text", "text": "hi"}],
    }


def _tool_call_event_dict(*, tool_name: str) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": "evt_2",
        "thread_id": "t_1",
        "run_id": None,
        "author": {"role": "user", "id": "u_1", "name": "U", "metadata": {}},
        "created_at": now,
        "metadata": {},
        "client_id": None,
        "recipients": None,
        "type": "tool.call",
        "tool": {"id": "c_1", "name": tool_name, "arguments": {"ticker": "R"}},
    }


async def _noop_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={})


async def test_on_message_decorator_fires_on_matching_event() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_noop_handler)),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    received: list[Any] = []

    @client.on_message()
    async def handle(ctx: HandlerContext, _send: HandlerSend) -> None:
        received.append(ctx.event)

    await client.connect()
    raw_handler = sio.handlers["event"]
    await raw_handler(_message_event_dict(author_id="u_other", recipients=["a_me"]))
    assert len(received) == 1


async def test_on_message_decorator_respects_recipient_filter() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_noop_handler)),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    received: list[Any] = []

    @client.on_message()
    async def handle(ctx: HandlerContext, _send: HandlerSend) -> None:
        received.append(ctx.event)

    await client.connect()
    raw_handler = sio.handlers["event"]
    await raw_handler(_message_event_dict(author_id="u_other", recipients=["a_other"]))
    assert received == []


async def test_on_tool_call_with_name_filter() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    hits: list[Any] = []

    @client.on_tool_call("get_stock")
    async def handle(ctx: HandlerContext, _send: HandlerSend) -> None:
        hits.append(ctx.event)

    await client.connect()
    raw_handler = sio.handlers["event"]
    await raw_handler(_tool_call_event_dict(tool_name="get_stock"))
    await raw_handler(_tool_call_event_dict(tool_name="get_weather"))
    assert len(hits) == 1


async def test_on_tool_call_without_name_matches_any_tool() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    hits: list[Any] = []

    @client.on_tool_call()
    async def any_tool(ctx: HandlerContext, _send: HandlerSend) -> None:
        hits.append(ctx.event)

    await client.connect()
    raw_handler = sio.handlers["event"]
    await raw_handler(_tool_call_event_dict(tool_name="get_stock"))
    await raw_handler(_tool_call_event_dict(tool_name="get_weather"))
    assert len(hits) == 2


async def test_emitter_handler_routes_through_event_send() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    sio.ack_replies["event:send"] = {
        "event": {
            "id": "evt_reply",
            "thread_id": "t_1",
            "run_id": "run_1",
            "author": me.model_dump(mode="json"),
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": {},
            "client_id": None,
            "recipients": None,
            "type": "message",
            "content": [{"type": "text", "text": "pong"}],
        }
    }
    sio.ack_replies["run:begin"] = {"run_id": "run_1", "status": "running"}
    sio.ack_replies["run:end"] = {"run_id": "run_1", "status": "completed"}
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )

    @client.on_message()
    async def reply(_ctx: HandlerContext, send: HandlerSend):
        yield send.message(content=[TextPart(text="pong")])

    await client.connect()
    raw_handler = sio.handlers["event"]
    await raw_handler(_message_event_dict(author_id="u_other", recipients=["a_me"]))

    emitted_names = [ev for ev, _ in sio.emitted]
    assert "event:send" in emitted_names


async def test_send_message_emits_on_socket() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    now = datetime.now(UTC).isoformat()
    sio.ack_replies["message:send"] = {
        "event": {
            "id": "evt_1",
            "thread_id": "t_1",
            "run_id": None,
            "author": me.model_dump(mode="json"),
            "created_at": now,
            "metadata": {},
            "client_id": "c_1",
            "recipients": None,
            "type": "message",
            "content": [{"type": "text", "text": "hi"}],
        }
    }
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    await client.connect()
    event = await client.send_message(
        "t_1", content=[TextPart(text="hi")], client_id="c_1"
    )
    assert event.type == "message"
    emitted_event, emitted_data = sio.emitted[0]
    assert emitted_event == "message:send"
    assert emitted_data["thread_id"] == "t_1"
    assert emitted_data["draft"]["client_id"] == "c_1"


async def test_disconnect_tears_down_both_transports() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    http = httpx.AsyncClient()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=http,
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    await client.connect()
    await client.disconnect()
    assert sio.disconnected is True
    assert http.is_closed


async def test_reconnect_switches_url_and_preserves_handlers() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    sio1 = FakeSioClient()
    sio2 = FakeSioClient()
    client = ChatClient(
        base_url="http://chat-a.test",
        identity=me,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_noop_handler)),
        socket_transport=SocketTransport(base_url="http://chat-a.test", sio_client=sio1),
    )
    received: list[Any] = []

    @client.on_message()
    async def handle(ctx: HandlerContext, _send: HandlerSend) -> None:
        received.append(ctx.event)

    await client.connect()
    # Switch to a different URL with a different fake sio
    await client.reconnect(
        base_url="http://chat-b.test",
        socket_transport=SocketTransport(base_url="http://chat-b.test", sio_client=sio2),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_noop_handler)),
    )
    # The handler registered BEFORE reconnect must still fire after.
    raw_handler = sio2.handlers["event"]
    await raw_handler(_message_event_dict(author_id="u_other", recipients=["a_me"]))
    assert len(received) == 1
    assert sio1.disconnected is True
    assert sio2.connected_url == "http://chat-b.test"
