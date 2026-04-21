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
async def setup(clean_db: asyncpg.Pool) -> tuple[AsyncClient, str]:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    return client, create.json()["id"]


async def test_list_members_includes_creator(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    resp = await client.get(f"/chat/threads/{thread_id}/members")
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["identity_id"] == "u_alice"


async def test_add_member(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    resp = await client.post(
        f"/chat/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "user",
                "id": "u_bob",
                "name": "Bob",
                "metadata": {},
            }
        },
    )
    assert resp.status_code == 201

    list_resp = await client.get(f"/chat/threads/{thread_id}/members")
    ids = {m["identity_id"] for m in list_resp.json()}
    assert ids == {"u_alice", "u_bob"}


async def test_remove_member(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    await client.post(
        f"/chat/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "user",
                "id": "u_bob",
                "name": "Bob",
                "metadata": {},
            }
        },
    )
    resp = await client.delete(f"/chat/threads/{thread_id}/members/u_bob")
    assert resp.status_code == 204

    list_resp = await client.get(f"/chat/threads/{thread_id}/members")
    ids = {m["identity_id"] for m in list_resp.json()}
    assert ids == {"u_alice"}
