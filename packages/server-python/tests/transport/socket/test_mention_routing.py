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
from rfnry_chat_protocol import AssistantIdentity, Identity, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
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
    return chat_server.mount(fastapi)


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


async def _create_thread_with_members(base: str) -> str:
    async with httpx.AsyncClient(base_url=base) as http:
        thread_id = (await http.post("/chat/threads", json={"tenant": {"org": "A"}})).json()["id"]
        for member_id, name in [("engineer", "Engineer"), ("coordinator", "Coordinator")]:
            ai = AssistantIdentity(id=member_id, name=name, metadata={"tenant": {"org": "A"}})
            await http.post(
                f"/chat/threads/{thread_id}/members",
                json={"identity": ai.model_dump(mode="json"), "role": "member"},
            )
    return thread_id


async def test_socket_event_send_with_single_mention_sets_recipients(live: tuple[str, ChatServer]) -> None:
    base, _ = live
    thread_id = await _create_thread_with_members(base)

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_id})

    response = await client.call(
        "event:send",
        {
            "thread_id": thread_id,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": "hi @engineer"}],
            },
        },
    )

    assert "event" in response, response
    assert response["event"]["recipients"] == ["engineer"]
    await client.disconnect()


async def test_socket_event_send_with_two_mentions_one_event(live: tuple[str, ChatServer]) -> None:
    base, _ = live
    thread_id = await _create_thread_with_members(base)

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_id})

    async with httpx.AsyncClient(base_url=base) as http:
        before = (await http.get(f"/chat/threads/{thread_id}/events")).json()["items"]

    response = await client.call(
        "event:send",
        {
            "thread_id": thread_id,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": "@engineer @coordinator look"}],
            },
        },
    )
    assert "event" in response, response
    assert response["event"]["recipients"] == ["engineer", "coordinator"]

    async with httpx.AsyncClient(base_url=base) as http:
        after = (await http.get(f"/chat/threads/{thread_id}/events")).json()["items"]

    assert len(after) == len(before) + 1
    await client.disconnect()


async def test_socket_event_send_explicit_recipients_not_overwritten(live: tuple[str, ChatServer]) -> None:
    base, _ = live
    thread_id = await _create_thread_with_members(base)

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_id})

    response = await client.call(
        "event:send",
        {
            "thread_id": thread_id,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": "@engineer hi"}],
                "recipients": ["coordinator"],
            },
        },
    )
    assert "event" in response, response
    assert response["event"]["recipients"] == ["coordinator"]
    await client.disconnect()


async def test_socket_event_send_unknown_mention_no_routing(live: tuple[str, ChatServer]) -> None:
    base, _ = live
    thread_id = await _create_thread_with_members(base)

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_id})

    response = await client.call(
        "event:send",
        {
            "thread_id": thread_id,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": "@nobody hi"}],
            },
        },
    )
    assert "event" in response, response
    assert response["event"]["recipients"] is None
    await client.disconnect()


async def test_socket_event_send_content_preserved(live: tuple[str, ChatServer]) -> None:
    base, _ = live
    thread_id = await _create_thread_with_members(base)

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_id})

    text = "@engineer please look — and respond??"
    response = await client.call(
        "event:send",
        {
            "thread_id": thread_id,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": text}],
            },
        },
    )
    assert "event" in response, response
    assert response["event"]["content"][0]["text"] == text
    assert response["event"]["recipients"] == ["engineer"]
    await client.disconnect()


async def test_socket_event_send_lifecycle_rejected_before_mention_parse(live: tuple[str, ChatServer]) -> None:

    base, _ = live
    thread_id = await _create_thread_with_members(base)

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_id})

    response = await client.call(
        "event:send",
        {
            "thread_id": thread_id,
            "event": {
                "type": "run.started",
                "content": [{"type": "text", "text": "@engineer"}],
            },
        },
    )
    error = response.get("error", {})
    assert error.get("code") in ("invalid_request", "forbidden"), response
    await client.disconnect()


async def test_socket_event_send_dispatcher_filter_drops_non_recipients(live: tuple[str, ChatServer]) -> None:

    base, _ = live
    thread_id = await _create_thread_with_members(base)

    client = socketio.AsyncClient()
    received: list[dict[str, Any]] = []

    @client.on("event", namespace="/")
    async def _on_event(payload: dict[str, Any]) -> None:
        received.append(payload)

    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_id})

    await client.call(
        "event:send",
        {
            "thread_id": thread_id,
            "event": {
                "type": "message",
                "content": [{"type": "text", "text": "@engineer hi"}],
            },
        },
    )
    await asyncio.sleep(0.3)
    matching = [p for p in received if p.get("type") == "message" and p.get("recipients") == ["engineer"]]
    assert matching, f"expected broadcast with recipients=[engineer], got: {received}"
    await client.disconnect()


async def test_socket_message_send_with_mention_sets_recipients(live: tuple[str, ChatServer]) -> None:
    base, _ = live
    thread_id = await _create_thread_with_members(base)

    client = socketio.AsyncClient()
    await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")
    await client.call("thread:join", {"thread_id": thread_id})

    response = await client.call(
        "message:send",
        {
            "thread_id": thread_id,
            "draft": {
                "client_id": "cid_1",
                "content": [{"type": "text", "text": "ping @coordinator"}],
            },
        },
    )
    assert "event" in response, response
    assert response["event"]["recipients"] == ["coordinator"]
    await client.disconnect()
