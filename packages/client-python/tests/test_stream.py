from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity, UserIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.handler.stream import Stream
from rfnry_chat_client.transport.socket import SocketTransport


def _build_client() -> tuple[ChatClient, FakeSioClient]:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    now = datetime.now(UTC).isoformat()

    def _event_payload(event_type: str, content_field: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": "evt_stream",
            "thread_id": "t_1",
            "run_id": "run_1",
            "author": me.model_dump(mode="json"),
            "created_at": now,
            "metadata": {},
            "client_id": None,
            "recipients": None,
            "type": event_type,
        }
        if event_type == "message":
            payload["content"] = content_field
        else:
            payload["content"] = content_field
        return payload

    sio.ack_replies["stream:start"] = {"ok": True}
    sio.ack_replies["stream:delta"] = {"ok": True}
    sio.ack_replies["stream:end"] = {"ok": True}
    sio.ack_replies["event:send"] = {"event": _event_payload("message", [{"type": "text", "text": "hello world"}])}
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )
    return client, sio


async def test_stream_lifecycle_emits_start_deltas_end_and_final_event() -> None:
    client, sio = _build_client()
    me = client.identity
    assert isinstance(me, AssistantIdentity)

    stream = Stream(
        client=client,
        thread_id="t_1",
        run_id="run_1",
        author=me,
        target_type="message",
    )
    async with stream as s:
        await s.write("hello ")
        await s.write("world")

    events = [name for name, _ in sio.emitted]
    assert events == ["stream:start", "stream:delta", "stream:delta", "stream:end", "event:send"]

    final_event_payload = sio.emitted[-1][1]
    assert final_event_payload["thread_id"] == "t_1"
    assert final_event_payload["event"]["type"] == "message"
    assert final_event_payload["event"]["content"][0]["text"] == "hello world"


async def test_stream_error_exit_emits_end_frame_with_error_and_skips_final_event() -> None:
    client, sio = _build_client()
    me = client.identity
    assert isinstance(me, AssistantIdentity)

    with pytest.raises(RuntimeError, match="boom"):
        async with Stream(
            client=client,
            thread_id="t_1",
            run_id="run_1",
            author=me,
            target_type="message",
        ) as s:
            await s.write("partial")
            raise RuntimeError("boom")

    events = [name for name, _ in sio.emitted]
    assert "event:send" not in events
    end_frame = next(payload for name, payload in sio.emitted if name == "stream:end")
    assert end_frame["error"]["code"] == "handler_error"
    assert "boom" in end_frame["error"]["message"]


async def test_reasoning_stream_final_event_is_reasoning() -> None:
    client, sio = _build_client()
    now = datetime.now(UTC).isoformat()
    me = client.identity
    assert isinstance(me, AssistantIdentity)

    sio.ack_replies["event:send"] = {
        "event": {
            "id": "evt_stream",
            "thread_id": "t_1",
            "run_id": "run_1",
            "author": me.model_dump(mode="json"),
            "created_at": now,
            "metadata": {},
            "client_id": None,
            "recipients": None,
            "type": "reasoning",
            "content": "deciding",
        }
    }
    async with Stream(
        client=client,
        thread_id="t_1",
        run_id="run_1",
        author=me,
        target_type="reasoning",
    ) as s:
        await s.write("deciding")

    final_payload = sio.emitted[-1][1]
    assert final_payload["event"]["type"] == "reasoning"
    assert final_payload["event"]["content"] == "deciding"


async def test_stream_allows_non_assistant_identity() -> None:
    """Any identity can stream — role is server-validated, not client-gated.

    Mirrors React's compile-time-only restriction: the TypeScript type system
    narrows the author, but there is no runtime block. The server remains the
    authority on who is permitted to stream in a given thread.
    """
    client, sio = _build_client()
    user = UserIdentity(id="u_human", name="Human")

    now = datetime.now(UTC).isoformat()
    sio.ack_replies["event:send"] = {
        "event": {
            "id": "evt_stream",
            "thread_id": "t_1",
            "run_id": "run_1",
            "author": user.model_dump(mode="json"),
            "created_at": now,
            "metadata": {},
            "client_id": None,
            "recipients": None,
            "type": "message",
            "content": [{"type": "text", "text": "hi"}],
        }
    }

    async with Stream(
        client=client,
        thread_id="t_1",
        run_id="run_1",
        author=user,
        target_type="message",
    ) as s:
        await s.write("hi")

    events = [name for name, _ in sio.emitted]
    assert events == ["stream:start", "stream:delta", "stream:end", "event:send"]
    start_frame = next(payload for name, payload in sio.emitted if name == "stream:start")
    assert start_frame["author"]["role"] == "user"
    assert start_frame["author"]["id"] == "u_human"


async def test_handler_send_message_stream_requires_run() -> None:
    from rfnry_chat_client.handler.send import HandlerSend

    client, _ = _build_client()
    me = client.identity
    send = HandlerSend(thread_id="t_1", author=me, run_id=None, client=client)
    with pytest.raises(RuntimeError, match="run_id"):
        send.message_stream()


async def test_handler_send_message_stream_requires_client() -> None:
    from rfnry_chat_client.handler.send import HandlerSend

    me = AssistantIdentity(id="a_me", name="Me")
    send = HandlerSend(thread_id="t_1", author=me, run_id="run_1", client=None)
    with pytest.raises(RuntimeError, match="ChatClient"):
        send.message_stream()


async def test_message_stream_recipients_forwarded_to_final_event() -> None:
    """message_stream(recipients=[...]) sets recipients on the finalized MessageEvent."""
    from rfnry_chat_client.handler.send import HandlerSend

    client, sio = _build_client()
    me = client.identity
    assert isinstance(me, AssistantIdentity)

    now = datetime.now(UTC).isoformat()
    sio.ack_replies["event:send"] = {
        "event": {
            "id": "evt_stream",
            "thread_id": "t_1",
            "run_id": "run_1",
            "author": me.model_dump(mode="json"),
            "created_at": now,
            "metadata": {},
            "client_id": None,
            "recipients": ["u_x"],
            "type": "message",
            "content": [{"type": "text", "text": "hello"}],
        }
    }

    send = HandlerSend(thread_id="t_1", author=me, run_id="run_1", client=client)
    async with send.message_stream(recipients=["u_x"]) as stream:
        await stream.write("hello")

    assert stream.finalized_event is not None
    assert stream.finalized_event.recipients == ["u_x"]
