from __future__ import annotations

import asyncpg
import pytest
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


@pytest.fixture
def alice() -> UserIdentity:
    return UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})


@pytest.fixture
async def client(clean_db: asyncpg.Pool, alice: UserIdentity) -> AsyncClient:
    store = PostgresChatStore(pool=clean_db)
    app = _build_app(store, alice)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_post_threads_creates_a_thread(client: AsyncClient) -> None:
    resp = await client.post(
        "/chat/threads",
        json={"tenant": {"org": "A"}, "metadata": {"title": "test"}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["tenant"] == {"org": "A"}
    assert body["metadata"] == {"title": "test"}
    assert body["id"].startswith("th_")


async def test_get_threads_filters_by_tenant(client: AsyncClient) -> None:
    await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    await client.post("/chat/threads", json={"tenant": {"org": "A", "ws": "X"}})
    await client.post("/chat/threads", json={"tenant": {"org": "B"}})

    resp = await client.get("/chat/threads")
    assert resp.status_code == 200
    items = resp.json()["items"]
    tenants = [t["tenant"] for t in items]
    assert {"org": "A"} in tenants
    assert {"org": "B"} not in tenants
    assert {"org": "A", "ws": "X"} not in tenants


async def test_get_thread_by_id(client: AsyncClient) -> None:
    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.get(f"/chat/threads/{thread_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == thread_id


async def test_get_thread_404(client: AsyncClient) -> None:
    resp = await client.get("/chat/threads/th_nope")
    assert resp.status_code == 404


async def test_patch_thread_metadata(client: AsyncClient) -> None:
    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.patch(f"/chat/threads/{thread_id}", json={"metadata": {"locked": True}})
    assert resp.status_code == 200
    assert resp.json()["metadata"] == {"locked": True}


async def test_patch_thread_tenant_emits_event(client: AsyncClient) -> None:
    create = await client.post("/chat/threads", json={"tenant": {}})
    thread_id = create.json()["id"]

    resp = await client.patch(f"/chat/threads/{thread_id}", json={"tenant": {"org": "A"}})
    assert resp.status_code == 200

    events_resp = await client.get(f"/chat/threads/{thread_id}/events")
    events = events_resp.json()["items"]
    tenant_changed = [e for e in events if e["type"] == "thread.tenant_changed"]
    assert len(tenant_changed) == 1
    assert tenant_changed[0]["from"] == {}
    assert tenant_changed[0]["to"] == {"org": "A"}


async def test_create_thread_rejects_tenant_missing_namespace_keys(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice_id = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice_id

    chat_server = ChatServer(
        store=store,
        authenticate=auth,
        namespace_keys=["org"],
    )
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/chat/threads", json={"tenant": {}})
        assert r.status_code == 400
        assert "namespace_keys" in r.text


async def test_rest_rejects_identity_missing_namespace_key(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    charlie = UserIdentity(id="u_charlie", name="Charlie", metadata={})

    async def auth(_h: HandshakeData) -> Identity:
        return charlie

    chat_server = ChatServer(
        store=store,
        authenticate=auth,
        namespace_keys=["org"],
    )
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/chat/threads")
        assert r.status_code == 403
        assert "namespace" in r.text.lower()


async def test_post_threads_same_client_id_is_idempotent(client: AsyncClient) -> None:
    first = await client.post(
        "/chat/threads",
        json={"tenant": {"org": "A"}, "client_id": "ck-stable"},
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = await client.post(
        "/chat/threads",
        json={"tenant": {"org": "A"}, "client_id": "ck-stable"},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first_id


async def test_post_threads_client_id_scoped_per_caller(clean_db: asyncpg.Pool) -> None:
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "A"}})
    store = PostgresChatStore(pool=clean_db)

    alice_app = _build_app(store, alice)
    bob_app = _build_app(store, bob)

    async with AsyncClient(transport=ASGITransport(app=alice_app), base_url="http://test") as alice_client:
        a_resp = await alice_client.post(
            "/chat/threads",
            json={"tenant": {"org": "A"}, "client_id": "ck-shared"},
        )
    assert a_resp.status_code == 201
    alice_thread_id = a_resp.json()["id"]

    async with AsyncClient(transport=ASGITransport(app=bob_app), base_url="http://test") as bob_client:
        b_resp = await bob_client.post(
            "/chat/threads",
            json={"tenant": {"org": "A"}, "client_id": "ck-shared"},
        )
    assert b_resp.status_code == 201
    assert b_resp.json()["id"] != alice_thread_id


async def test_post_threads_without_client_id_creates_fresh_each_time(
    client: AsyncClient,
) -> None:
    r1 = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    r2 = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


async def test_delete_thread(client: AsyncClient) -> None:
    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={"client_id": "x", "content": [{"type": "text", "text": "hi"}]},
    )

    resp = await client.delete(f"/chat/threads/{thread_id}")
    assert resp.status_code == 204

    get_resp = await client.get(f"/chat/threads/{thread_id}")
    assert get_resp.status_code == 404


async def test_clear_thread_events_wipes_history_keeps_thread(client: AsyncClient) -> None:
    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={"client_id": "m1", "content": [{"type": "text", "text": "hi"}]},
    )
    await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={"client_id": "m2", "content": [{"type": "text", "text": "again"}]},
    )
    events = await client.get(f"/chat/threads/{thread_id}/events")
    assert len(events.json()["items"]) == 2

    resp = await client.delete(f"/chat/threads/{thread_id}/events")
    assert resp.status_code == 204

    # Thread still exists
    get_resp = await client.get(f"/chat/threads/{thread_id}")
    assert get_resp.status_code == 200
    # History is gone
    events = await client.get(f"/chat/threads/{thread_id}/events")
    assert events.json()["items"] == []


async def test_clear_thread_events_404_on_unknown_thread(client: AsyncClient) -> None:
    resp = await client.delete("/chat/threads/th_nope/events")
    assert resp.status_code == 404


async def test_clear_thread_events_tenant_mismatch_404(clean_db: asyncpg.Pool) -> None:
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "B"}})

    alice_store = PostgresChatStore(pool=clean_db)
    alice_app = _build_app(alice_store, alice)
    async with AsyncClient(transport=ASGITransport(app=alice_app), base_url="http://test") as alice_client:
        create = await alice_client.post("/chat/threads", json={"tenant": {"org": "A"}})
        thread_id = create.json()["id"]

    # Bob's identity tenant doesn't match the thread
    bob_store = PostgresChatStore(pool=clean_db)
    bob_app = _build_app(bob_store, bob)
    async with AsyncClient(transport=ASGITransport(app=bob_app), base_url="http://test") as bob_client:
        resp = await bob_client.delete(f"/chat/threads/{thread_id}/events")
        assert resp.status_code == 404
