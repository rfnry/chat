from __future__ import annotations

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def client_with_authorize(
    clean_db: asyncpg.Pool,
) -> tuple[AsyncClient, list[tuple[str, str, str]]]:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    calls: list[tuple[str, str, str]] = []

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    async def authorize(
        identity: Identity,
        thread_id: str,
        action: str,
        *,
        target_id: str | None = None,
    ) -> bool:
        calls.append((identity.id, thread_id, action))
        return action != "thread.delete"

    chat_server = ChatServer(store=store, authenticate=auth, authorize=authorize)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), calls


async def test_authorize_called_on_read(
    client_with_authorize: tuple[AsyncClient, list[tuple[str, str, str]]],
) -> None:
    client, calls = client_with_authorize
    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.get(f"/chat/threads/{thread_id}")
    assert resp.status_code == 200
    assert (alice_action := ("u_alice", thread_id, "thread.read")) in calls
    del alice_action


async def test_authorize_can_deny_an_action(
    client_with_authorize: tuple[AsyncClient, list[tuple[str, str, str]]],
) -> None:
    client, _calls = client_with_authorize
    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.delete(f"/chat/threads/{thread_id}")
    assert resp.status_code == 403
    assert "not authorized: thread.delete" in resp.json()["detail"]


async def test_no_authorize_callback_allows_everything(
    clean_db: asyncpg.Pool,
) -> None:
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
    thread_id = create.json()["id"]

    resp = await client.delete(f"/chat/threads/{thread_id}")
    assert resp.status_code == 204
