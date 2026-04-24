from __future__ import annotations

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore
from rfnry_chat_server.transport.rest.threads import MAX_THREADS_LIMIT


def _build_app(store: PostgresChatStore, identity: Identity) -> FastAPI:
    async def auth(_h: HandshakeData) -> Identity:
        return identity

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    return app


async def test_list_threads_clamps_oversize_limit_to_max(
    clean_db: asyncpg.Pool,
) -> None:
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    store = PostgresChatStore(pool=clean_db)

    called = {}
    original = store.list_threads

    async def spy(*args, **kwargs):
        called["limit"] = kwargs.get("limit")
        return await original(*args, **kwargs)

    store.list_threads = spy  # type: ignore[method-assign]

    app = _build_app(store, alice)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/chat/threads?limit=999999")
        assert r.status_code == 200

    assert called["limit"] == MAX_THREADS_LIMIT


async def test_list_threads_preserves_reasonable_limit(
    clean_db: asyncpg.Pool,
) -> None:
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    store = PostgresChatStore(pool=clean_db)

    called = {}
    original = store.list_threads

    async def spy(*args, **kwargs):
        called["limit"] = kwargs.get("limit")
        return await original(*args, **kwargs)

    store.list_threads = spy  # type: ignore[method-assign]

    app = _build_app(store, alice)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/chat/threads?limit=25")
        assert r.status_code == 200

    assert called["limit"] == 25


async def test_list_threads_clamps_non_positive_limit_to_one(
    clean_db: asyncpg.Pool,
) -> None:
    """Zero or negative limits are treated as the minimum (1)."""
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    store = PostgresChatStore(pool=clean_db)

    called = {}
    original = store.list_threads

    async def spy(*args, **kwargs):
        called["limit"] = kwargs.get("limit")
        return await original(*args, **kwargs)

    store.list_threads = spy  # type: ignore[method-assign]

    app = _build_app(store, alice)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/chat/threads?limit=0")
        assert r.status_code == 200

    assert called["limit"] == 1
