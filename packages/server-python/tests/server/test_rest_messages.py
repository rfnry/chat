from __future__ import annotations

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def client(clean_db: asyncpg.Pool) -> AsyncClient:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_send_message_appends_event(client: AsyncClient) -> None:
    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "cid_1",
            "content": [{"type": "text", "text": "hello"}],
        },
    )
    assert resp.status_code == 201
    event = resp.json()
    assert event["type"] == "message"
    assert event["thread_id"] == thread_id
    assert event["author"]["id"] == "u_alice"
    assert event["client_id"] == "cid_1"
    assert event["content"][0]["text"] == "hello"


async def test_list_events_returns_appended(client: AsyncClient) -> None:
    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    for i in range(3):
        await client.post(
            f"/chat/threads/{thread_id}/messages",
            json={
                "client_id": f"cid_{i}",
                "content": [{"type": "text", "text": f"m{i}"}],
            },
        )

    resp = await client.get(f"/chat/threads/{thread_id}/events")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 3
    assert [e["client_id"] for e in body["items"]] == ["cid_0", "cid_1", "cid_2"]


async def test_send_message_requires_membership(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "A"}})

    async def auth_alice(_h: HandshakeData) -> Identity:
        return alice

    async def auth_bob(_h: HandshakeData) -> Identity:
        return bob

    app_alice = FastAPI()
    chat_server_alice = ChatServer(store=store, authenticate=auth_alice)
    app_alice.state.chat_server = chat_server_alice
    app_alice.include_router(chat_server_alice.router, prefix="/chat")
    client_alice = AsyncClient(transport=ASGITransport(app=app_alice), base_url="http://a")

    app_bob = FastAPI()
    chat_server_bob = ChatServer(store=store, authenticate=auth_bob)
    app_bob.state.chat_server = chat_server_bob
    app_bob.include_router(chat_server_bob.router, prefix="/chat")
    client_bob = AsyncClient(transport=ASGITransport(app=app_bob), base_url="http://b")

    create = await client_alice.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client_bob.post(
        f"/chat/threads/{thread_id}/messages",
        json={"client_id": "x", "content": [{"type": "text", "text": "hi"}]},
    )
    assert resp.status_code == 403
