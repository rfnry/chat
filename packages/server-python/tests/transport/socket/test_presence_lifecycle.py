"""Presence lifecycle: presence:joined / presence:left refcount semantics.

Covers the 0→1 joined edge (Task 2.4) and the 1→0 left edge (Task 2.5). Design
pins: the joining socket itself must not receive its own joined frame
(skip_sid), and intermediate opens/closes (2→1, 1→2) must not re-broadcast.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
import socketio
import uvicorn
from fastapi import FastAPI
from rfnry_chat_protocol import Identity, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
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
    return chat_server.mount(fastapi)


async def _settle() -> None:
    """Yield control so socket events propagate to clients."""
    await asyncio.sleep(0.1)


@pytest.fixture
async def live_multi_identity(clean_db: asyncpg.Pool) -> AsyncIterator[tuple[str, ChatServer]]:
    """Live server that authenticates each client to a different identity,
    selected via the `user` key in the Socket.IO handshake `auth` payload.

    This lets one test spin up an observer socket plus multiple sockets for a
    second identity and verify the 0→1 edge behavior without tenancy getting
    in the way (both identities share the default tenant)."""
    observer = UserIdentity(id="observer", name="Obs", metadata={})
    agent = UserIdentity(id="agent-a", name="Agent A", metadata={})
    identities: dict[str, Identity] = {"observer": observer, "agent-a": agent}

    async def auth(handshake: HandshakeData) -> Identity | None:
        user_id: str | None = None
        if isinstance(handshake.auth, dict):
            raw = handshake.auth.get("user")
            if isinstance(raw, str):
                user_id = raw
        return identities.get(user_id) if user_id else None

    store = PostgresChatStore(pool=clean_db)
    chat_server = ChatServer(store=store, authenticate=auth)
    asgi = _wire(chat_server)
    server = _Server(asgi)
    base = await server.start()
    try:
        yield base, chat_server
    finally:
        await server.stop()


async def test_first_socket_broadcasts_joined_second_silent(
    live_multi_identity: tuple[str, ChatServer],
) -> None:
    """0→1 transition fires `presence:joined` exactly once; a second socket
    for the same identity does not re-broadcast (refcount semantics)."""
    base, _ = live_multi_identity

    observer_received: list[tuple[str, dict[str, Any]]] = []
    obs = socketio.AsyncClient()

    @obs.on("presence:joined")
    async def on_joined(data: dict[str, Any]) -> None:
        observer_received.append(("joined", data))

    @obs.on("presence:left")
    async def on_left(data: dict[str, Any]) -> None:
        observer_received.append(("left", data))

    await obs.connect(
        base,
        transports=["websocket"],
        socketio_path="/chat/ws",
        auth={"user": "observer"},
    )

    a1 = socketio.AsyncClient()
    a2 = socketio.AsyncClient()
    try:
        await a1.connect(
            base,
            transports=["websocket"],
            socketio_path="/chat/ws",
            auth={"user": "agent-a"},
        )
        await _settle()
        joined = [e for e in observer_received if e[0] == "joined"]
        assert len(joined) == 1, f"expected exactly one joined, got {joined!r}"
        assert joined[0][1]["identity"]["id"] == "agent-a"

        # Second socket for same identity must not re-broadcast.
        await a2.connect(
            base,
            transports=["websocket"],
            socketio_path="/chat/ws",
            auth={"user": "agent-a"},
        )
        await _settle()
        joined = [e for e in observer_received if e[0] == "joined"]
        assert len(joined) == 1, f"second socket triggered extra joined: {joined!r}"
    finally:
        with contextlib.suppress(Exception):
            await a1.disconnect()
        with contextlib.suppress(Exception):
            await a2.disconnect()
        with contextlib.suppress(Exception):
            await obs.disconnect()


async def test_joining_socket_does_not_receive_own_joined(
    live_multi_identity: tuple[str, ChatServer],
) -> None:
    """skip_sid prevents the joining socket from getting its own joined event."""
    base, _ = live_multi_identity

    self_received: list[dict[str, Any]] = []
    client = socketio.AsyncClient()

    @client.on("presence:joined")
    async def on_joined(data: dict[str, Any]) -> None:
        self_received.append(data)

    try:
        await client.connect(
            base,
            transports=["websocket"],
            socketio_path="/chat/ws",
            auth={"user": "agent-a"},
        )
        await _settle()
        assert self_received == [], f"joining socket received its own joined: {self_received!r}"
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


async def test_last_socket_broadcasts_left(
    live_multi_identity: tuple[str, ChatServer],
) -> None:
    """1→0 transition fires `presence:left` exactly once. Closing a non-last
    socket (2→1) stays silent; only the final close broadcasts."""
    base, _ = live_multi_identity

    observer_received: list[tuple[str, dict[str, Any]]] = []
    obs = socketio.AsyncClient()

    @obs.on("presence:left")
    async def on_left(data: dict[str, Any]) -> None:
        observer_received.append(("left", data))

    await obs.connect(
        base,
        transports=["websocket"],
        socketio_path="/chat/ws",
        auth={"user": "observer"},
    )

    a1 = socketio.AsyncClient()
    a2 = socketio.AsyncClient()
    try:
        await a1.connect(
            base,
            transports=["websocket"],
            socketio_path="/chat/ws",
            auth={"user": "agent-a"},
        )
        await a2.connect(
            base,
            transports=["websocket"],
            socketio_path="/chat/ws",
            auth={"user": "agent-a"},
        )
        await _settle()

        # Closing one of two sockets for agent-a must NOT broadcast left
        # (refcount 2→1).
        await a1.disconnect()
        await _settle()
        left = [e for e in observer_received if e[0] == "left"]
        assert len(left) == 0, f"2→1 disconnect leaked a presence:left: {left!r}"

        # Closing the final socket (1→0) broadcasts exactly one presence:left.
        await a2.disconnect()
        await _settle()
        left = [e for e in observer_received if e[0] == "left"]
        assert len(left) == 1, f"expected exactly one left, got {left!r}"
        assert left[0][1]["identity"]["id"] == "agent-a"
    finally:
        with contextlib.suppress(Exception):
            await a1.disconnect()
        with contextlib.suppress(Exception):
            await a2.disconnect()
        with contextlib.suppress(Exception):
            await obs.disconnect()
