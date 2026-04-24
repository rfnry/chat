"""Guard: event:send must reject a run_id that belongs to a different thread."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
import pytest
import socketio
import uvicorn
from fastapi import FastAPI
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


class _Server:
    def __init__(self, app: Any) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off")
        self._server = uvicorn.Server(config)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> str:
        self._task = asyncio.create_task(self._server.serve())
        for _ in range(500):
            if self._server.started:
                break
            await asyncio.sleep(0.01)
        assert self._server.started
        sock = self._server.servers[0].sockets[0]
        port = sock.getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, timeout=5)


def _make_chat_server(store: PostgresChatStore) -> ChatServer:
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    return ChatServer(store=store, authenticate=auth)


def _wire(chat_server: ChatServer) -> Any:
    fastapi = FastAPI()
    fastapi.state.chat_server = chat_server
    fastapi.include_router(chat_server.router, prefix="/chat")
    return chat_server.mount_socketio(fastapi)


@pytest.fixture
async def live(clean_db: asyncpg.Pool) -> AsyncIterator[tuple[str, ChatServer]]:
    store = PostgresChatStore(pool=clean_db)
    chat_server = _make_chat_server(store)
    asgi = _wire(chat_server)

    server = _Server(asgi)
    base = await server.start()
    try:
        yield base, chat_server
    finally:
        await server.stop()


async def test_event_send_rejects_run_id_from_different_thread(live: tuple[str, ChatServer]) -> None:
    """Sending event:send into thread A with a run_id owned by thread B must
    return an invalid_request error — not silently persist the cross-thread FK."""
    base, _ = live

    async with httpx.AsyncClient(base_url=base) as http:
        thread_a = (await http.post("/chat/threads", json={"tenant": {"org": "A"}})).json()["id"]
        thread_b = (await http.post("/chat/threads", json={"tenant": {"org": "A"}})).json()["id"]

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_a})
    await client.call("thread:join", {"thread_id": thread_b})

    # Open a run in thread B — capture the run_id.
    run_b = await client.call("run:begin", {"thread_id": thread_b})
    run_id_b = run_b["run_id"]
    assert isinstance(run_id_b, str)

    # Attempt to attach an event in thread A using the run from thread B.
    response = await client.call(
        "event:send",
        {
            "thread_id": thread_a,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": "cross-thread probe"}],
                "run_id": run_id_b,
            },
        },
    )

    error = response.get("error", {})
    assert error.get("code") == "invalid_request", f"unexpected response: {response}"
    assert "run_id" in error.get("message", "") or "thread" in error.get("message", "")

    await client.disconnect()


async def test_event_send_accepts_run_id_from_same_thread(live: tuple[str, ChatServer]) -> None:
    """Sanity check: run_id from the same thread must be accepted."""
    base, _ = live

    async with httpx.AsyncClient(base_url=base) as http:
        thread_a = (await http.post("/chat/threads", json={"tenant": {"org": "A"}})).json()["id"]

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_a})

    run_a = await client.call("run:begin", {"thread_id": thread_a})
    run_id_a = run_a["run_id"]

    response = await client.call(
        "event:send",
        {
            "thread_id": thread_a,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": "same-thread ok"}],
                "run_id": run_id_a,
            },
        },
    )

    assert "event" in response, f"expected success, got: {response}"
    assert response["event"]["run_id"] == run_id_a

    await client.disconnect()


async def test_event_send_accepts_null_run_id(live: tuple[str, ChatServer]) -> None:
    """Events without a run_id must continue to work unchanged."""
    base, _ = live

    async with httpx.AsyncClient(base_url=base) as http:
        thread_a = (await http.post("/chat/threads", json={"tenant": {"org": "A"}})).json()["id"]

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_a})

    response = await client.call(
        "event:send",
        {
            "thread_id": thread_a,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": "no run_id"}],
            },
        },
    )

    assert "event" in response, f"expected success, got: {response}"
    assert response["event"]["run_id"] is None

    await client.disconnect()


async def test_event_send_rejects_nonexistent_run_id(live: tuple[str, ChatServer]) -> None:
    """A run_id that does not exist in the store must also be rejected."""
    base, _ = live

    async with httpx.AsyncClient(base_url=base) as http:
        thread_a = (await http.post("/chat/threads", json={"tenant": {"org": "A"}})).json()["id"]

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_a})

    response = await client.call(
        "event:send",
        {
            "thread_id": thread_a,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": "ghost run"}],
                "run_id": "run_does_not_exist",
            },
        },
    )

    error = response.get("error", {})
    assert error.get("code") == "invalid_request", f"unexpected response: {response}"

    await client.disconnect()
