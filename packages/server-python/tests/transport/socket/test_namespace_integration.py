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
from rfnry_chat_protocol import AssistantIdentity, Identity, UserIdentity

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


def _make_chat_server_with_ns(store: PostgresChatStore, identity: Identity) -> ChatServer:
    async def auth(_: HandshakeData) -> Identity:
        return identity

    return ChatServer(
        store=store,
        authenticate=auth,
        namespace_keys=["org"],
    )


def _make_chat_server_multi_identity(store: PostgresChatStore, identities: dict[str, Identity]) -> ChatServer:
    """ChatServer whose authenticate callback dispatches on the connect-time
    auth payload (Socket.IO) or the `x-user` HTTP header (REST). Used by
    cross-namespace isolation tests that need more than one identity on the
    same live server."""

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
        if user_id is None:
            return None
        return identities.get(user_id)

    return ChatServer(
        store=store,
        authenticate=auth,
        namespace_keys=["org"],
    )


def _wire(chat_server: ChatServer) -> Any:
    fastapi = FastAPI()
    fastapi.state.chat_server = chat_server
    fastapi.include_router(chat_server.router, prefix="/chat")
    return chat_server.mount(fastapi)


@pytest.fixture
async def live_ns_a(
    clean_db: asyncpg.Pool,
) -> AsyncIterator[tuple[str, ChatServer]]:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    chat_server = _make_chat_server_with_ns(store, alice)
    asgi = _wire(chat_server)

    server = _Server(asgi)
    base = await server.start()
    try:
        yield base, chat_server
    finally:
        await server.stop()


async def test_connect_to_matching_namespace_succeeds(
    live_ns_a: tuple[str, ChatServer],
) -> None:
    base, _ = live_ns_a
    client = socketio.AsyncClient()
    await client.connect(base, namespaces=["/A"], transports=["websocket"], socketio_path="/chat/ws")
    assert client.connected
    await client.disconnect()


async def test_connect_to_wrong_namespace_rejected(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    # Identity belongs to org B, but the client will try to connect to /A
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "B"}})
    chat_server = _make_chat_server_with_ns(store, bob)
    asgi = _wire(chat_server)
    server = _Server(asgi)
    base = await server.start()
    try:
        client = socketio.AsyncClient()
        with pytest.raises(socketio.exceptions.ConnectionError):
            await client.connect(base, namespaces=["/A"], transports=["websocket"], socketio_path="/chat/ws")
    finally:
        await server.stop()


async def test_connect_to_root_rejected_when_keys_set(
    live_ns_a: tuple[str, ChatServer],
) -> None:
    base, _ = live_ns_a
    client = socketio.AsyncClient()
    # Connecting without an explicit namespace defaults to `/`, which has
    # zero segments and therefore fails parse_namespace_path.
    with pytest.raises(socketio.exceptions.ConnectionError):
        await client.connect(base, transports=["websocket"], socketio_path="/chat/ws")


async def test_join_thread_in_matching_namespace_succeeds(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    chat_server = _make_chat_server_with_ns(store, alice)
    asgi = _wire(chat_server)
    server = _Server(asgi)
    base = await server.start()
    try:
        # Create a thread in org A via REST
        async with httpx.AsyncClient(base_url=base) as http:
            create = await http.post("/chat/threads", json={"tenant": {"org": "A"}})
            thread_id = create.json()["id"]

        # Client connects to /A and can see it
        client = socketio.AsyncClient()
        await client.connect(base, namespaces=["/A"], transports=["websocket"], socketio_path="/chat/ws")
        join = await client.call("thread:join", {"thread_id": thread_id}, namespace="/A")
        assert join["thread_id"] == thread_id
        await client.disconnect()
        # The cross-namespace "another client in /B gets not_found" case is
        # covered by test_broadcast_events_do_not_leak_across_namespaces
        # (which exercises the full broadcast isolation path, not just the
        # thread-level gate) and by test_join_thread_with_mismatched_ns_
        # tenant_returns_not_found (which exercises the thread-level gate
        # against a foreign-tenant thread).
    finally:
        await server.stop()


async def test_broadcast_events_do_not_leak_across_namespaces(
    clean_db: asyncpg.Pool,
) -> None:
    """The load-bearing defense-in-depth proof: a message broadcast inside
    `/A` reaches `/A` subscribers but never leaks to a client subscribed on
    `/B`, and vice versa. This is the property that makes `namespace_keys`
    worth shipping — everything else is just "another check on top of the
    existing gates." This test verifies the Socket.IO transport layer
    actually isolates the two namespaces at broadcast time."""

    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "B"}})
    chat_server = _make_chat_server_multi_identity(store, {"alice": alice, "bob": bob})
    asgi = _wire(chat_server)
    server = _Server(asgi)
    base = await server.start()
    try:
        # Each user creates a thread in their own org via REST.
        async with httpx.AsyncClient(base_url=base) as http:
            r_a = await http.post(
                "/chat/threads",
                json={"tenant": {"org": "A"}},
                headers={"x-user": "alice"},
            )
            assert r_a.status_code in (200, 201), r_a.text
            thread_a_id = r_a.json()["id"]

            r_b = await http.post(
                "/chat/threads",
                json={"tenant": {"org": "B"}},
                headers={"x-user": "bob"},
            )
            assert r_b.status_code in (200, 201), r_b.text
            thread_b_id = r_b.json()["id"]

        alice_events: list[dict[str, Any]] = []
        bob_events: list[dict[str, Any]] = []

        alice_client = socketio.AsyncClient()
        bob_client = socketio.AsyncClient()

        @alice_client.on("event", namespace="/A")
        async def on_alice_event(data: dict[str, Any]) -> None:
            alice_events.append(data)

        @bob_client.on("event", namespace="/B")
        async def on_bob_event(data: dict[str, Any]) -> None:
            bob_events.append(data)

        await alice_client.connect(
            base,
            namespaces=["/A"],
            auth={"user": "alice"},
            transports=["websocket"],
            socketio_path="/chat/ws",
        )
        await bob_client.connect(
            base,
            namespaces=["/B"],
            auth={"user": "bob"},
            transports=["websocket"],
            socketio_path="/chat/ws",
        )

        # Each client joins their own thread.
        join_a = await alice_client.call("thread:join", {"thread_id": thread_a_id}, namespace="/A")
        assert join_a["thread_id"] == thread_a_id
        join_b = await bob_client.call("thread:join", {"thread_id": thread_b_id}, namespace="/B")
        assert join_b["thread_id"] == thread_b_id

        # Alice posts a message to her thread via REST.
        async with httpx.AsyncClient(base_url=base) as http:
            r = await http.post(
                f"/chat/threads/{thread_a_id}/messages",
                json={
                    "client_id": "c_a1",
                    "content": [{"type": "text", "text": "hi from org A"}],
                },
                headers={"x-user": "alice"},
            )
            assert r.status_code in (200, 201), r.text

        # Wait up to ~1.5s for alice's client to receive the event.
        for _ in range(30):
            if alice_events:
                break
            await asyncio.sleep(0.05)

        # Alice saw her own message.
        assert len(alice_events) == 1
        assert alice_events[0]["client_id"] == "c_a1"
        assert alice_events[0]["type"] == "message"
        # Bob MUST NOT have seen it — the whole point of the feature.
        assert bob_events == []

        # Now bob posts to his thread and we verify the mirror case.
        async with httpx.AsyncClient(base_url=base) as http:
            r = await http.post(
                f"/chat/threads/{thread_b_id}/messages",
                json={
                    "client_id": "c_b1",
                    "content": [{"type": "text", "text": "hi from org B"}],
                },
                headers={"x-user": "bob"},
            )
            assert r.status_code in (200, 201), r.text

        for _ in range(30):
            if bob_events:
                break
            await asyncio.sleep(0.05)

        assert len(bob_events) == 1
        assert bob_events[0]["client_id"] == "c_b1"
        # Alice's event list is still just her own message.
        assert len(alice_events) == 1

        await alice_client.disconnect()
        await bob_client.disconnect()
    finally:
        await server.stop()


async def test_join_thread_with_mismatched_ns_tenant_returns_not_found(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    # Alice has tenant `{org: A}` — she'll connect to `/A`. We then
    # manually insert a thread whose tenant is `{org: B}` into the
    # store and verify that joining it over WS returns not_found, even
    # though it exists.
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    chat_server = _make_chat_server_with_ns(store, alice)
    asgi = _wire(chat_server)
    server = _Server(asgi)
    base = await server.start()
    try:
        # Bypass the REST 400 gate by inserting directly (simulates
        # stale data from before namespace_keys was enabled).
        async with clean_db.acquire() as conn:
            await conn.execute(
                "INSERT INTO threads (id, tenant, metadata) VALUES ($1, $2, $3)",
                "th_foreign",
                '{"org": "B"}',
                "{}",
            )
            await conn.execute(
                "INSERT INTO thread_members (thread_id, identity_id, identity, role, added_by) "
                "VALUES ($1, $2, $3, 'member', $4)",
                "th_foreign",
                "u_alice",
                '{"role": "user", "id": "u_alice", "name": "Alice", "metadata": {"tenant": {"org": "A"}}}',
                '{"role": "user", "id": "u_alice", "name": "Alice", "metadata": {"tenant": {"org": "A"}}}',
            )

        client = socketio.AsyncClient()
        await client.connect(base, namespaces=["/A"], transports=["websocket"], socketio_path="/chat/ws")
        result = await client.call("thread:join", {"thread_id": "th_foreign"}, namespace="/A")
        assert result.get("error", {}).get("code") == "not_found"
        await client.disconnect()
    finally:
        await server.stop()


async def test_thread_invited_delivered_to_inbox_room_end_to_end(
    clean_db: asyncpg.Pool,
) -> None:
    """Regression anchor for the proactive-agents invite pipeline.

    Alice connects as a user. Bot authenticates as a distinct assistant
    identity, creates a thread via REST, then invites Alice by POSTing to
    `/chat/threads/{id}/members`. Alice's socket must receive exactly one
    `thread:invited` frame, routed via the per-identity `inbox:<id>` room
    that `ThreadNamespace.on_connect` auto-joins. Exercises the full chain:
    REST handler → ChatServer.publish_thread_invited → SocketIOBroadcaster
    → Socket.IO room filtering → AsyncClient.on('thread:invited')."""

    store = PostgresChatStore(pool=clean_db)

    alice = UserIdentity(id="u_alice", name="Alice", metadata={})
    bot = AssistantIdentity(id="a_bot", name="Bot", metadata={})

    async def auth(handshake: HandshakeData) -> Identity | None:
        # Socket.IO clients pass creds in the `auth={...}` handshake payload;
        # REST clients pass them in the `Authorization: Bearer ...` header.
        token: str = ""
        if isinstance(handshake.auth, dict):
            raw = handshake.auth.get("token")
            if isinstance(raw, str):
                token = raw
        if not token:
            header_val = handshake.headers.get("authorization", "")
            if header_val.startswith("Bearer "):
                token = header_val[len("Bearer ") :].strip()
        if token == "alice-token":
            return alice
        if token == "bot-token":
            return bot
        return None

    chat_server = ChatServer(store=store, authenticate=auth)
    asgi = _wire(chat_server)
    server = _Server(asgi)
    base = await server.start()

    received: list[dict[str, Any]] = []
    invited = asyncio.Event()

    alice_sio = socketio.AsyncClient()

    @alice_sio.on("thread:invited")
    async def on_invited(data: dict[str, Any]) -> None:
        received.append(data)
        invited.set()

    try:
        await alice_sio.connect(
            base,
            auth={"token": "alice-token"},
            transports=["websocket"],
            socketio_path="/chat/ws",
        )

        bot_headers = {"authorization": "Bearer bot-token"}
        async with httpx.AsyncClient(base_url=base, headers=bot_headers) as http:
            create = await http.post("/chat/threads", json={})
            assert create.status_code == 201, create.text
            thread_id = create.json()["id"]

            add = await http.post(
                f"/chat/threads/{thread_id}/members",
                json={
                    "identity": {
                        "role": "user",
                        "id": "u_alice",
                        "name": "Alice",
                        "metadata": {},
                    }
                },
            )
            assert add.status_code == 201, add.text

        await asyncio.wait_for(invited.wait(), timeout=5)

        assert len(received) == 1
        frame = received[0]
        assert frame["thread"]["id"] == thread_id
        assert frame["added_member"]["id"] == "u_alice"
        assert frame["added_by"]["id"] == "a_bot"
        assert frame["added_by"]["role"] == "assistant"
    finally:
        if alice_sio.connected:
            await alice_sio.disconnect()
        await server.stop()
