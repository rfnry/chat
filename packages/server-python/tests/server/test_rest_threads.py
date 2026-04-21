from __future__ import annotations

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
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
