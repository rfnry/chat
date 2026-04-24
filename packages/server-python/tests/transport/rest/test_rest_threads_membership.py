from __future__ import annotations

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


def _build_app(store: PostgresChatStore, identity: Identity) -> FastAPI:
    async def auth(_h: HandshakeData) -> Identity:
        return identity

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    return app


async def test_list_threads_hides_non_member_threads_in_same_tenant(
    clean_db: asyncpg.Pool,
) -> None:
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "A"}})

    store = PostgresChatStore(pool=clean_db)

    # Alice creates a thread. She is auto-added as member.
    alice_app = _build_app(store, alice)
    async with AsyncClient(transport=ASGITransport(app=alice_app), base_url="http://test") as alice_client:
        r = await alice_client.post("/chat/threads", json={"tenant": {"org": "A"}})
        assert r.status_code == 201
        alice_thread_id = r.json()["id"]

    # Bob, same tenant but NOT a member, lists threads. Should not see Alice's thread.
    bob_app = _build_app(store, bob)
    async with AsyncClient(transport=ASGITransport(app=bob_app), base_url="http://test") as bob_client:
        r = await bob_client.get("/chat/threads")
        assert r.status_code == 200
        ids = [t["id"] for t in r.json()["items"]]
        assert alice_thread_id not in ids


async def test_list_threads_shows_threads_where_caller_is_member(
    clean_db: asyncpg.Pool,
) -> None:
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "A"}})

    store = PostgresChatStore(pool=clean_db)

    alice_app = _build_app(store, alice)
    async with AsyncClient(transport=ASGITransport(app=alice_app), base_url="http://test") as alice_client:
        r = await alice_client.post("/chat/threads", json={"tenant": {"org": "A"}})
        thread_id = r.json()["id"]
        # Alice adds Bob.
        r = await alice_client.post(
            f"/chat/threads/{thread_id}/members",
            json={"identity": bob.model_dump(mode="json"), "role": "member"},
        )
        assert r.status_code in (200, 201)

    bob_app = _build_app(store, bob)
    async with AsyncClient(transport=ASGITransport(app=bob_app), base_url="http://test") as bob_client:
        r = await bob_client.get("/chat/threads")
        assert r.status_code == 200
        ids = [t["id"] for t in r.json()["items"]]
        assert thread_id in ids
