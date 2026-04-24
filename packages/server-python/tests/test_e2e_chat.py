from __future__ import annotations

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


def _client_for(store: PostgresChatStore, identity: Identity) -> AsyncClient:
    async def auth(_h: HandshakeData) -> Identity:
        return identity

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_full_chat_scenario(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)

    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "A"}})

    alice_client = _client_for(store, alice)
    bob_client = _client_for(store, bob)

    resp = await alice_client.post("/chat/threads", json={"tenant": {"org": "A"}})
    assert resp.status_code == 201
    thread_id = resp.json()["id"]

    resp = await alice_client.get("/chat/threads")
    assert thread_id in [t["id"] for t in resp.json()["items"]]

    resp = await bob_client.get(f"/chat/threads/{thread_id}/events")
    assert resp.status_code == 403

    resp = await alice_client.post(
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

    await alice_client.post(
        f"/chat/threads/{thread_id}/messages",
        json={"client_id": "a1", "content": [{"type": "text", "text": "hi bob"}]},
    )
    await bob_client.post(
        f"/chat/threads/{thread_id}/messages",
        json={"client_id": "b1", "content": [{"type": "text", "text": "hi alice"}]},
    )

    resp = await bob_client.get(f"/chat/threads/{thread_id}/events")
    items = resp.json()["items"]
    message_events = [e for e in items if e["type"] == "message"]
    assert [e["client_id"] for e in message_events] == ["a1", "b1"]
    assert message_events[0]["author"]["id"] == "u_alice"
    assert message_events[1]["author"]["id"] == "u_bob"

    resp = await alice_client.delete(f"/chat/threads/{thread_id}/members/u_bob")
    assert resp.status_code == 204
    resp = await bob_client.get(f"/chat/threads/{thread_id}/events")
    assert resp.status_code == 403

    resp = await alice_client.delete(f"/chat/threads/{thread_id}")
    assert resp.status_code == 204
    resp = await alice_client.get(f"/chat/threads/{thread_id}")
    assert resp.status_code == 404
