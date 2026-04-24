from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.memory.store import InMemoryChatStore


def _build_app(server: ChatServer) -> FastAPI:
    app = FastAPI()
    app.state.chat_server = server
    app.include_router(server.router, prefix="/chat")
    return app


def _server_with_identity(identity: Identity, **kwargs: object) -> ChatServer:
    async def auth(_h: HandshakeData) -> Identity:
        return identity

    return ChatServer(store=InMemoryChatStore(), authenticate=auth, **kwargs)  # type: ignore[arg-type]


async def test_returns_snapshot_excluding_caller() -> None:
    alice = UserIdentity(id="u_alice", name="Alice", metadata={})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={})
    carol = UserIdentity(id="u_carol", name="Carol", metadata={})

    server = _server_with_identity(carol)
    await server.presence.add("u_alice", "sid1", alice, tenant_path="/")
    await server.presence.add("u_bob", "sid2", bob, tenant_path="/")

    app = _build_app(server)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/chat/presence")

    assert resp.status_code == 200
    body = resp.json()
    ids = {m["id"] for m in body["members"]}
    assert ids == {"u_alice", "u_bob"}


async def test_snapshot_scoped_to_callers_tenant() -> None:
    caller = UserIdentity(
        id="u_x",
        name="X",
        metadata={"tenant": {"organization": "acme"}},
    )
    server = _server_with_identity(caller, namespace_keys=["organization"])

    alice = UserIdentity(
        id="u_alice",
        name="Alice",
        metadata={"tenant": {"organization": "acme"}},
    )
    bob = UserIdentity(
        id="u_bob",
        name="Bob",
        metadata={"tenant": {"organization": "widgets"}},
    )
    await server.presence.add("u_alice", "sid1", alice, tenant_path="/acme")
    await server.presence.add("u_bob", "sid2", bob, tenant_path="/widgets")

    app = _build_app(server)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/chat/presence")

    assert resp.status_code == 200
    body = resp.json()
    ids = {m["id"] for m in body["members"]}
    assert ids == {"u_alice"}


async def test_snapshot_empty_when_no_one_online() -> None:
    caller = UserIdentity(id="u_x", name="X", metadata={})
    server = _server_with_identity(caller)

    app = _build_app(server)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/chat/presence")

    assert resp.status_code == 200
    assert resp.json() == {"members": []}


async def test_snapshot_excludes_caller_when_caller_is_also_present() -> None:
    caller = UserIdentity(id="u_x", name="X", metadata={})
    server = _server_with_identity(caller)

    alice = UserIdentity(id="u_alice", name="Alice", metadata={})
    await server.presence.add("u_alice", "sid1", alice, tenant_path="/")
    # Caller also has a live socket — still excluded from their own snapshot.
    await server.presence.add("u_x", "sid_caller", caller, tenant_path="/")

    app = _build_app(server)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/chat/presence")

    assert resp.status_code == 200
    body = resp.json()
    ids = {m["id"] for m in body["members"]}
    assert ids == {"u_alice"}
