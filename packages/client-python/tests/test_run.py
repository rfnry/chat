from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity, Run

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


async def test_begin_run_returns_run_id_string() -> None:
    """R12.2: begin_run returns the run_id as a string, not a hydrated Run.
    Saves the extra REST GET previously needed for hydration."""
    sio = FakeSioClient()
    sio.ack_replies["run:begin"] = {"run_id": "run_abc", "status": "running"}
    client = _build_client(sio)

    result = await client.begin_run("t_1", triggered_by_event_id="evt_1")
    assert result == "run_abc", f"expected str run_id, got {result!r}"
    assert isinstance(result, str), f"expected str, got {type(result).__name__}"


async def test_end_run_returns_none() -> None:
    """R12.2: end_run returns None (was: hydrated Run via extra REST GET)."""
    sio = FakeSioClient()
    sio.ack_replies["run:end"] = {"run_id": "run_abc", "status": "completed"}
    client = _build_client(sio)

    result = await client.end_run("run_abc")
    assert result is None, f"expected None, got {result!r}"


async def test_get_run_returns_hydrated_run() -> None:
    """R12.2: callers that need the full Run object call get_run(id)
    explicitly. This is the only path that pays the REST GET cost."""
    now = datetime.now(UTC).isoformat()
    run_payload = {
        "id": "run_abc",
        "thread_id": "t_1",
        "actor": {"role": "assistant", "id": "a_me", "name": "Me", "metadata": {}},
        "triggered_by": {"role": "assistant", "id": "a_me", "name": "Me", "metadata": {}},
        "status": "running",
        "started_at": now,
        "completed_at": None,
        "error": None,
        "idempotency_key": None,
        "metadata": {},
    }

    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/chat/runs/run_abc"
        return httpx.Response(200, json=run_payload)

    sio = FakeSioClient()
    client = ChatClient(
        base_url="http://chat.test",
        identity=AssistantIdentity(id="a_me", name="Me"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )

    run = await client.get_run("run_abc")
    assert isinstance(run, Run), f"expected Run, got {type(run).__name__}"
    assert run.id == "run_abc"
    assert run.status == "running"
