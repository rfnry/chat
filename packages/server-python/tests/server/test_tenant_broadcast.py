"""Tests for the tenant-scoped thread:created / thread:deleted fanout.

ChatServer.publish_thread_{created,deleted} iterate the live socket-identity
map (provided by ChatSocketIO.connected_identities()) and call the
broadcaster's *_to_sids method with only the tenant-matching (sid, namespace)
pairs. We stub the socketio layer with a tiny shim because spinning up a real
socket.io server per test is too much setup for a pure logic check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@dataclass
class _StubSocketIO:
    """Minimal stand-in for ChatSocketIO — only exposes connected_identities().
    ChatServer.publish_thread_{created,deleted} never touches .sio, so the
    shim is enough."""

    connected: list[tuple[str, str, Identity]] = field(default_factory=list)

    def connected_identities(self) -> list[tuple[str, str, Identity]]:
        return list(self.connected)


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


async def test_publish_thread_created_fans_to_tenant_matching_only(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = _mk_user("u_alice", {"organization": "acme", "workspace": "legal"})
    app, chat_server, rec = _build_app(store, alice)

    # Three connected sockets: one that matches, one with wrong workspace,
    # one with a wildcard workspace (should also match).
    matching = _mk_user("u_matching", {"organization": "acme", "workspace": "legal"})
    wrong_ws = _mk_user("u_wrong_ws", {"organization": "acme", "workspace": "finance"})
    wildcard = _mk_user("u_wildcard", {"organization": "acme", "workspace": "*"})
    chat_server._socketio = _StubSocketIO(
        connected=[
            ("sid_matching", "/", matching),
            ("sid_wrong_ws", "/", wrong_ws),
            ("sid_wildcard", "/", wildcard),
        ]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/chat/threads",
            json={"tenant": {"organization": "acme", "workspace": "legal"}},
        )
    assert resp.status_code == 201

    assert len(rec.thread_created_fanouts) == 1
    _thread, targets = rec.thread_created_fanouts[0]
    sids = sorted(sid for sid, _ns in targets)
    assert sids == ["sid_matching", "sid_wildcard"]


async def test_publish_thread_deleted_fans_with_pre_delete_tenant(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = _mk_user("u_alice", {"organization": "acme"})
    app, chat_server, rec = _build_app(store, alice)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        create = await c.post("/chat/threads", json={"tenant": {"organization": "acme"}})
        thread_id = create.json()["id"]

        observer = _mk_user("u_observer", {"organization": "acme"})
        chat_server._socketio = _StubSocketIO(
            connected=[("sid_observer", "/", observer)]
        )

        resp = await c.delete(f"/chat/threads/{thread_id}")
    assert resp.status_code == 204

    assert len(rec.thread_deleted_fanouts) == 1
    broadcast_thread_id, targets = rec.thread_deleted_fanouts[0]
    assert broadcast_thread_id == thread_id
    assert [(sid, ns) for sid, ns in targets] == [("sid_observer", "/")]


async def test_reuse_via_client_id_does_not_refire_broadcast(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = _mk_user("u_alice", {"organization": "acme"})
    app, chat_server, rec = _build_app(store, alice)
    chat_server._socketio = _StubSocketIO(
        connected=[("sid_observer", "/", _mk_user("u_observer", {"organization": "acme"}))]
    )

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

    # Only the first create should have fired the fanout.
    assert len(rec.thread_created_fanouts) == 1


async def test_no_connected_sockets_skips_fanout(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = _mk_user("u_alice", {"organization": "acme"})
    app, chat_server, rec = _build_app(store, alice)
    chat_server._socketio = _StubSocketIO(connected=[])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/chat/threads", json={"tenant": {"organization": "acme"}})
    assert resp.status_code == 201
    # No matching sockets → empty targets → broadcaster short-circuit means no record.
    assert rec.thread_created_fanouts == []


@pytest.mark.asyncio
async def test_no_socketio_attached_skips_fanout(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = _mk_user("u_alice", {"organization": "acme"})
    app, chat_server, rec = _build_app(store, alice)
    # Do NOT set chat_server._socketio. ChatServer.publish_thread_created
    # short-circuits cleanly when sockets layer isn't mounted.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/chat/threads", json={"tenant": {"organization": "acme"}})
    assert resp.status_code == 201
    assert rec.thread_created_fanouts == []
