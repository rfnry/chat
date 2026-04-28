from __future__ import annotations

from typing import Any

import pytest
from rfnry_chat_protocol import AssistantIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.transport.socket import SocketTransportError

ME = AssistantIdentity(id="a_me", name="Me")


class _StubSocket:
    def __init__(self) -> None:
        self.cancel_calls: list[str] = []
        self.next_reply: dict[str, Any] | Exception = {"run_id": "run_x", "cancelled": True}

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        self.cancel_calls.append(run_id)
        if isinstance(self.next_reply, Exception):
            raise self.next_reply
        return self.next_reply


def _client(socket: _StubSocket) -> ChatClient:
    async def auth() -> dict[str, Any]:
        return {}

    return ChatClient(
        base_url="http://test",
        identity=ME,
        authenticate=auth,
        socket_transport=socket,  # type: ignore[arg-type]
    )


async def test_cancel_run_calls_socket_run_cancel() -> None:
    socket = _StubSocket()
    client = _client(socket)
    result = await client.cancel_run("run_x")
    assert socket.cancel_calls == ["run_x"]
    assert result == {"run_id": "run_x", "cancelled": True}


async def test_cancel_run_propagates_not_found() -> None:
    socket = _StubSocket()
    socket.next_reply = SocketTransportError("not_found", "run not found")
    client = _client(socket)
    with pytest.raises(SocketTransportError, match="not found"):
        await client.cancel_run("run_missing")
    assert socket.cancel_calls == ["run_missing"]


async def test_cancel_run_propagates_forbidden() -> None:
    socket = _StubSocket()
    socket.next_reply = SocketTransportError("forbidden", "not authorized")
    client = _client(socket)
    with pytest.raises(SocketTransportError, match="not authorized"):
        await client.cancel_run("run_other")


async def test_cancel_run_idempotent_on_already_terminal() -> None:
    socket = _StubSocket()
    socket.next_reply = {"run_id": "run_done", "cancelled": True}
    client = _client(socket)
    result = await client.cancel_run("run_done")
    assert result["cancelled"] is True
