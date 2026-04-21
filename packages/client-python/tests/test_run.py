from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.transport.socket import SocketTransport


def _build_client(sio: FakeSioClient) -> ChatClient:
    me = AssistantIdentity(id="a_me", name="Me")
    return ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )


async def test_run_connects_and_holds_until_cancelled() -> None:
    sio = FakeSioClient()
    client = _build_client(sio)

    task = asyncio.create_task(client.run())
    for _ in range(50):
        if sio.connected_url is not None:
            break
        await asyncio.sleep(0.01)
    assert sio.connected_url == "http://chat.test"

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert sio.disconnected is True


async def test_run_invokes_on_connect_hook() -> None:
    sio = FakeSioClient()
    client = _build_client(sio)

    called = asyncio.Event()

    async def on_connect() -> None:
        called.set()

    task = asyncio.create_task(client.run(on_connect=on_connect))
    try:
        await asyncio.wait_for(called.wait(), timeout=1.0)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_run_retries_then_raises_after_exhaustion() -> None:
    class _AlwaysFails:
        async def connect(
            self,
            url: str,
            *,
            auth: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
            transports: list[str] | None = None,
            socketio_path: str | None = None,
        ) -> None:
            raise OSError("nope")

        async def disconnect(self) -> None:
            pass

        def on(self, event: str, handler: Any = None) -> Any:
            return None

        async def emit(self, event: str, data: Any = None) -> None:
            pass

        async def call(self, event: str, data: Any = None, *, timeout: float | None = None) -> Any:
            return {}

    me = AssistantIdentity(id="a_me", name="Me")
    sio = _AlwaysFails()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )

    with pytest.raises(ConnectionError, match="failed to connect"):
        await client.run(connect_retries=3, connect_backoff_seconds=0.0)


async def test_run_disconnects_when_on_connect_raises() -> None:
    sio = FakeSioClient()
    client = _build_client(sio)

    async def on_connect() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await client.run(on_connect=on_connect)
    assert sio.disconnected is True
