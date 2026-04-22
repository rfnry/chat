from __future__ import annotations

from typing import Any

import pytest
from conftest import FakeSioClient as _FakeSioClient

from rfnry_chat_client.transport.socket import SocketTransport


async def test_connect_passes_auth_and_path() -> None:
    sio = _FakeSioClient()

    async def auth() -> dict[str, Any]:
        return {"auth": {"token": "t"}, "headers": {"x-env": "test"}}

    transport = SocketTransport(
        base_url="http://chat.test",
        sio_client=sio,
        authenticate=auth,
    )
    await transport.connect()
    assert sio.connected_url == "http://chat.test"
    assert sio.connected_auth == {"token": "t"}
    assert sio.headers_sent == {"x-env": "test"}


async def test_join_thread_emits_with_ack_and_returns_payload() -> None:
    sio = _FakeSioClient()
    sio.ack_replies["thread:join"] = {
        "thread_id": "t_1",
        "replayed": [],
        "replay_truncated": False,
    }
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)
    result = await transport.join_thread("t_1")
    assert sio.emitted == [("thread:join", {"thread_id": "t_1"})]
    assert result["thread_id"] == "t_1"


async def test_join_thread_with_since_cursor() -> None:
    sio = _FakeSioClient()
    sio.ack_replies["thread:join"] = {"thread_id": "t_1", "replayed": [], "replay_truncated": False}
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)
    await transport.join_thread(
        "t_1", since={"created_at": "2026-04-21T00:00:00Z", "id": "evt_0"}
    )
    _event, data = sio.emitted[0]
    assert data["since"] == {"created_at": "2026-04-21T00:00:00Z", "id": "evt_0"}


async def test_join_thread_raises_on_error_payload() -> None:
    sio = _FakeSioClient()
    sio.ack_replies["thread:join"] = {"error": {"code": "forbidden", "message": "no"}}
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)
    with pytest.raises(Exception) as info:
        await transport.join_thread("t_1")
    assert "forbidden" in str(info.value)


async def test_leave_thread_emits() -> None:
    sio = _FakeSioClient()
    sio.ack_replies["thread:leave"] = {"thread_id": "t_1", "left": True}
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)
    await transport.leave_thread("t_1")
    assert sio.emitted == [("thread:leave", {"thread_id": "t_1"})]


async def test_send_message_emits_with_draft() -> None:
    sio = _FakeSioClient()
    sio.ack_replies["message:send"] = {"event": {"id": "evt_1"}}
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)
    draft = {"client_id": "c_1", "content": [{"type": "text", "text": "hi"}]}
    reply = await transport.send_message("t_1", draft)
    assert sio.emitted == [("message:send", {"thread_id": "t_1", "draft": draft})]
    assert reply["event"]["id"] == "evt_1"


async def test_on_raw_event_registers_handler() -> None:
    sio = _FakeSioClient()
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)

    received: list[dict[str, Any]] = []

    async def handler(payload: dict[str, Any]) -> None:
        received.append(payload)

    transport.on_raw_event("event", handler)
    fn = sio.handlers["event"][0]
    await fn({"id": "evt_1", "type": "message"})
    assert received == [{"id": "evt_1", "type": "message"}]


async def test_cancel_run_emits() -> None:
    sio = _FakeSioClient()
    sio.ack_replies["run:cancel"] = {"run_id": "run_1", "cancelled": True}
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)
    reply = await transport.cancel_run("run_1")
    assert sio.emitted == [("run:cancel", {"run_id": "run_1"})]
    assert reply["cancelled"] is True


async def test_disconnect_closes_socket() -> None:
    sio = _FakeSioClient()
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)
    await transport.disconnect()
    assert sio.disconnected is True
