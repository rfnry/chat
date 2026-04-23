"""R11.1/R11.2: tenant room join on connect + tenant-scoped broadcast isolation.

- namespace_keys=["org"]  → room is  tenant:/acme
- namespace_keys=None     → room is  tenant:/   (single-tenant sentinel)
- thread:created for tenant A must NOT reach a socket from tenant B
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
import pytest
import socketio
import uvicorn
from fastapi import FastAPI
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.broadcast.socketio import _tenant_room
from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


class _Server:
    def __init__(self, app: Any) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off")
        self._server = uvicorn.Server(config)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> str:
        self._task = asyncio.create_task(self._server.serve())
        for _ in range(500):
            if self._server.started:
                break
            await asyncio.sleep(0.01)
        assert self._server.started
        sock = self._server.servers[0].sockets[0]
        port = sock.getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, timeout=5)


def _wire(chat_server: ChatServer) -> Any:
    fastapi = FastAPI()
    fastapi.state.chat_server = chat_server
    fastapi.include_router(chat_server.router, prefix="/chat")
    return chat_server.mount_socketio(fastapi)


@pytest.fixture
async def live_with_ns_keys(clean_db: asyncpg.Pool) -> AsyncIterator[tuple[str, ChatServer]]:
    """Live server with namespace_keys=["org"]; authenticate always returns acme identity."""
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "acme"}})

    async def auth(_: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth, namespace_keys=["org"])
    asgi = _wire(chat_server)
    server = _Server(asgi)
    base = await server.start()
    try:
        yield base, chat_server
    finally:
        await server.stop()


@pytest.fixture
async def live_no_ns_keys(clean_db: asyncpg.Pool) -> AsyncIterator[tuple[str, ChatServer]]:
    """Live server with namespace_keys=None (single-tenant); authenticate always returns alice."""
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={})

    async def auth(_: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth)
    asgi = _wire(chat_server)
    server = _Server(asgi)
    base = await server.start()
    try:
        yield base, chat_server
    finally:
        await server.stop()


async def test_authenticated_socket_joins_tenant_room_on_connect(
    live_with_ns_keys: tuple[str, ChatServer],
) -> None:
    """R11.1: socket whose identity tenant is {"org": "acme"} receives a frame
    emitted to room tenant:/acme immediately after connect."""
    base, chat_server = live_with_ns_keys

    received: list[dict[str, Any]] = []
    got_frame = asyncio.Event()

    client = socketio.AsyncClient()

    @client.on("thread:created", namespace="/acme")
    async def on_created(data: dict[str, Any]) -> None:
        received.append(data)
        got_frame.set()

    await client.connect(
        base,
        namespaces=["/acme"],
        transports=["websocket"],
        socketio_path="/chat/ws",
    )

    # Emit directly to the tenant room from the server side.
    sio: socketio.AsyncServer = chat_server.broadcaster._sio  # type: ignore[attr-defined]
    tenant_room = _tenant_room({"org": "acme"}, namespace_keys=["org"])
    await sio.emit("thread:created", {"thread_id": "th_test"}, room=tenant_room, namespace="/acme")

    await asyncio.wait_for(got_frame.wait(), timeout=5)

    assert len(received) == 1
    assert received[0]["thread_id"] == "th_test"

    await client.disconnect()


async def test_single_tenant_socket_joins_root_tenant_room_on_connect(
    live_no_ns_keys: tuple[str, ChatServer],
) -> None:
    """R11.1 (single-tenant): socket joins tenant:/ when namespace_keys=None."""
    base, chat_server = live_no_ns_keys

    received: list[dict[str, Any]] = []
    got_frame = asyncio.Event()

    client = socketio.AsyncClient()

    @client.on("thread:created")
    async def on_created(data: dict[str, Any]) -> None:
        received.append(data)
        got_frame.set()

    await client.connect(
        base,
        transports=["websocket"],
        socketio_path="/chat/ws",
    )

    sio: socketio.AsyncServer = chat_server.broadcaster._sio  # type: ignore[attr-defined]
    tenant_room = _tenant_room({}, namespace_keys=None)
    assert tenant_room == "tenant:/"
    await sio.emit("thread:created", {"thread_id": "th_root"}, room=tenant_room, namespace="/")

    await asyncio.wait_for(got_frame.wait(), timeout=5)

    assert len(received) == 1
    assert received[0]["thread_id"] == "th_root"

    await client.disconnect()


async def test_thread_created_emits_only_to_matching_tenant_room(
    clean_db: asyncpg.Pool,
) -> None:
    """R11.2 (tenant isolation): a thread:created event for tenant A must
    NOT reach a socket from tenant B. The previous per-SID broadcast loop
    enforced this via filtering; the new room-based emit enforces it via
    Socket.IO room membership. This test pins the contract."""
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "acme"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "globex"}})
    identities: dict[str, Identity] = {"alice": alice, "bob": bob}

    async def auth(handshake: HandshakeData) -> Identity | None:
        user_id: str | None = None
        if isinstance(handshake.auth, dict):
            raw = handshake.auth.get("user")
            if isinstance(raw, str):
                user_id = raw
        if user_id is None:
            header_val = handshake.headers.get("x-user")
            if isinstance(header_val, str):
                user_id = header_val
        return identities.get(user_id) if user_id is not None else None

    store = PostgresChatStore(pool=clean_db)
    chat_server = ChatServer(store=store, authenticate=auth, namespace_keys=["org"])
    fastapi = FastAPI()
    fastapi.state.chat_server = chat_server
    fastapi.include_router(chat_server.router, prefix="/chat")
    asgi = chat_server.mount_socketio(fastapi)
    server = _Server(asgi)
    base = await server.start()
    try:
        alice_received: list[dict[str, Any]] = []
        bob_received: list[dict[str, Any]] = []
        alice_got = asyncio.Event()

        alice_client = socketio.AsyncClient()
        bob_client = socketio.AsyncClient()

        @alice_client.on("thread:created", namespace="/acme")
        async def on_alice_created(data: dict[str, Any]) -> None:
            alice_received.append(data)
            alice_got.set()

        @bob_client.on("thread:created", namespace="/globex")
        async def on_bob_created(data: dict[str, Any]) -> None:
            bob_received.append(data)

        await alice_client.connect(
            base,
            namespaces=["/acme"],
            transports=["websocket"],
            socketio_path="/chat/ws",
            auth={"user": "alice"},
        )
        await bob_client.connect(
            base,
            namespaces=["/globex"],
            transports=["websocket"],
            socketio_path="/chat/ws",
            auth={"user": "bob"},
        )

        async with httpx.AsyncClient(base_url=base) as http:
            resp = await http.post(
                "/chat/threads",
                json={"tenant": {"org": "acme"}},
                headers={"x-user": "alice"},
            )
            assert resp.status_code == 201

        await asyncio.wait_for(alice_got.wait(), timeout=5)

        assert len(alice_received) == 1
        assert len(bob_received) == 0
    finally:
        with contextlib.suppress(Exception):
            await alice_client.disconnect()
        with contextlib.suppress(Exception):
            await bob_client.disconnect()
        await server.stop()
