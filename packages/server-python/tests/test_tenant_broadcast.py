"""Tests for the tenant-scoped thread:created / thread:deleted broadcast.

ChatServer.publish_thread_{created,deleted} call the broadcaster's
broadcast_thread_{created,deleted} methods with the thread/tenant and
namespace_keys. The broadcaster (a SocketIOBroadcaster in production) then
emits to the deterministic tenant room that every authenticated socket joined
at connect time. We verify the contract via RecordingBroadcaster.
"""

from __future__ import annotations

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


def _mk_user(id_: str, tenant: dict[str, str]) -> UserIdentity:
    return UserIdentity(id=id_, name=id_, metadata={"tenant": tenant})


def _build_app(store: PostgresChatStore, caller: Identity) -> tuple[FastAPI, ChatServer, RecordingBroadcaster]:
    rec = RecordingBroadcaster()

    async def auth(_h: HandshakeData) -> Identity:
        return caller

    chat_server = ChatServer(store=store, authenticate=auth, broadcaster=rec)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    return app, chat_server, rec


async def test_publish_thread_created_records_broadcast(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = _mk_user("u_alice", {"organization": "acme"})
    app, _chat_server, rec = _build_app(store, alice)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/chat/threads", json={"tenant": {"organization": "acme"}})
    assert resp.status_code == 201
    thread_id = resp.json()["id"]

    assert len(rec.threads_created) == 1
    assert rec.threads_created[0].id == thread_id
    assert rec.threads_created[0].tenant == {"organization": "acme"}


async def test_publish_thread_deleted_records_broadcast_with_pre_delete_tenant(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = _mk_user("u_alice", {"organization": "acme"})
    app, _chat_server, rec = _build_app(store, alice)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post("/chat/threads", json={"tenant": {"organization": "acme"}})
        thread_id = create.json()["id"]
        resp = await c.delete(f"/chat/threads/{thread_id}")
    assert resp.status_code == 204

    assert len(rec.threads_deleted) == 1
    broadcast_thread_id, tenant = rec.threads_deleted[0]
    assert broadcast_thread_id == thread_id
    assert tenant == {"organization": "acme"}


async def test_reuse_via_client_id_does_not_refire_broadcast(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = _mk_user("u_alice", {"organization": "acme"})
    app, _chat_server, rec = _build_app(store, alice)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        first = await c.post(
            "/chat/threads",
            json={"tenant": {"organization": "acme"}, "client_id": "ck-stable"},
        )
        assert first.status_code == 201
        second = await c.post(
            "/chat/threads",
            json={"tenant": {"organization": "acme"}, "client_id": "ck-stable"},
        )
        assert second.status_code == 200  # reuse

    assert len(rec.threads_created) == 1


@pytest.mark.asyncio
async def test_no_broadcaster_skips_fanout(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = _mk_user("u_alice", {"organization": "acme"})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/chat/threads", json={"tenant": {"organization": "acme"}})
    assert resp.status_code == 201
