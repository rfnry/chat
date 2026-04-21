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
from rfnry_chat_protocol import Identity, TextPart, UserIdentity

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

    return ChatServer(store=store, authenticate=auth, run_timeout_seconds=5)


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


async def test_join_and_receive_event(live: tuple[str, ChatServer]) -> None:
    base, _ = live

    async with httpx.AsyncClient(base_url=base) as http:
        create = await http.post("/chat/threads", json={"tenant": {"org": "A"}})
        thread_id = create.json()["id"]

    received: list[dict[str, Any]] = []
    client = socketio.AsyncClient()

    @client.on("event")
    async def on_event(data: dict[str, Any]) -> None:
        received.append(data)

    await client.connect(base, transports=["websocket"])
    join = await client.call("thread:join", {"thread_id": thread_id})
    assert join["thread_id"] == thread_id
    assert join["replayed"] == []

    async with httpx.AsyncClient(base_url=base) as http:
        await http.post(
            f"/chat/threads/{thread_id}/messages",
            json={
                "client_id": "c1",
                "content": [{"type": "text", "text": "hi"}],
            },
        )

    for _ in range(50):
        if received:
            break
        await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0]["type"] == "message"
    assert received[0]["client_id"] == "c1"

    await client.disconnect()


async def test_resume_with_since_cursor(live: tuple[str, ChatServer]) -> None:
    base, _ = live

    async with httpx.AsyncClient(base_url=base) as http:
        create = await http.post("/chat/threads", json={"tenant": {"org": "A"}})
        thread_id = create.json()["id"]
        for i in range(3):
            await http.post(
                f"/chat/threads/{thread_id}/messages",
                json={
                    "client_id": f"c{i}",
                    "content": [{"type": "text", "text": f"m{i}"}],
                },
            )
        events = (await http.get(f"/chat/threads/{thread_id}/events")).json()["items"]

    cursor_event = events[0]
    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"])
    join = await client.call(
        "thread:join",
        {
            "thread_id": thread_id,
            "since": {
                "created_at": cursor_event["created_at"],
                "id": cursor_event["id"],
            },
        },
    )
    replayed_ids = [e["id"] for e in join["replayed"]]
    assert replayed_ids == [events[1]["id"], events[2]["id"]]

    await client.disconnect()


async def test_send_message_via_socket(live: tuple[str, ChatServer]) -> None:
    base, _ = live

    async with httpx.AsyncClient(base_url=base) as http:
        create = await http.post("/chat/threads", json={"tenant": {"org": "A"}})
        thread_id = create.json()["id"]

    received: list[dict[str, Any]] = []
    client = socketio.AsyncClient()

    @client.on("event")
    async def on_event(data: dict[str, Any]) -> None:
        received.append(data)

    await client.connect(base, transports=["websocket"])
    await client.call("thread:join", {"thread_id": thread_id})

    response = await client.call(
        "message:send",
        {
            "thread_id": thread_id,
            "draft": {
                "client_id": "c1",
                "content": [{"type": "text", "text": "from socket"}],
            },
        },
    )
    assert response["event"]["type"] == "message"
    assert response["event"]["client_id"] == "c1"

    for _ in range(50):
        if received:
            break
        await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0]["client_id"] == "c1"

    await client.disconnect()


async def test_invoke_via_socket(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth, run_timeout_seconds=5)

    @chat_server.assistant("a1")
    async def helper(ctx, send):
        yield send.message(content=[TextPart(text="hi from socket invoke")])

    asgi = _wire(chat_server)
    server = _Server(asgi)
    base = await server.start()
    try:
        async with httpx.AsyncClient(base_url=base) as http:
            create = await http.post("/chat/threads", json={"tenant": {"org": "A"}})
            thread_id = create.json()["id"]
            await http.post(
                f"/chat/threads/{thread_id}/members",
                json={
                    "identity": {
                        "role": "assistant",
                        "id": "a1",
                        "name": "Helper",
                        "metadata": {},
                    }
                },
            )

        client = socketio.AsyncClient()
        received: list[dict[str, Any]] = []

        @client.on("event")
        async def on_event(data: dict[str, Any]) -> None:
            received.append(data)

        await client.connect(base, transports=["websocket"])
        await client.call("thread:join", {"thread_id": thread_id})

        response = await client.call(
            "assistant:invoke",
            {"thread_id": thread_id, "assistant_ids": ["a1"]},
        )
        run_id = response["runs"][0]["id"]
        await chat_server.executor.await_run(run_id)

        for _ in range(50):
            if any(e["type"] == "run.completed" for e in received):
                break
            await asyncio.sleep(0.05)

        types = [e["type"] for e in received]
        assert "run.started" in types
        assert "message" in types
        assert "run.completed" in types

        await client.disconnect()
    finally:
        await server.stop()
