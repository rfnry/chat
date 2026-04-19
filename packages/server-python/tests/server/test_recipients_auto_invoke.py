from __future__ import annotations

import asyncio

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rfnry_chat_server.protocol.content import TextPart
from rfnry_chat_server.protocol.identity import Identity, UserIdentity
from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


async def _build_env(
    clean_db: asyncpg.Pool,
    *,
    auto_invoke_recipients: bool = True,
) -> tuple[ChatServer, AsyncClient, str, list[str]]:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ChatServer(
        store=store,
        authenticate=auth,
        run_timeout_seconds=5,
        auto_invoke_recipients=auto_invoke_recipients,
    )
    ran: list[str] = []

    @server.assistant("specialist")
    async def specialist(ctx, send):
        ran.append(ctx.run.id)
        yield send.message(content=[TextPart(text="specialist answered")])

    app = FastAPI()
    app.state.chat_server = server
    app.include_router(server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    await client.post(
        f"/chat/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "assistant",
                "id": "specialist",
                "name": "Specialist",
                "metadata": {},
            }
        },
    )
    return server, client, thread_id, ran


@pytest.fixture
async def env(clean_db: asyncpg.Pool) -> tuple[ChatServer, AsyncClient, str, list[str]]:
    return await _build_env(clean_db)


async def test_assistant_in_recipients_triggers_handler(
    env: tuple[ChatServer, AsyncClient, str, list[str]],
) -> None:
    server, client, thread_id, ran = env

    response = await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "hello specialist"}],
            "recipients": ["specialist"],
        },
    )
    assert response.status_code == 201
    assert response.json()["recipients"] == ["specialist"]

    for task in list(server.executor._tasks.values()):
        try:
            await task
        except Exception:
            pass

    assert len(ran) == 1


async def test_broadcast_does_not_auto_invoke(
    env: tuple[ChatServer, AsyncClient, str, list[str]],
) -> None:
    server, client, thread_id, ran = env

    response = await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "team chat, no target"}],
        },
    )
    assert response.status_code == 201
    assert response.json()["recipients"] is None

    await asyncio.sleep(0.1)
    for task in list(server.executor._tasks.values()):
        try:
            await task
        except Exception:
            pass

    assert ran == []


async def test_recipient_not_member_returns_400(
    env: tuple[ChatServer, AsyncClient, str, list[str]],
) -> None:
    _, client, thread_id, _ = env

    response = await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "ghost"}],
            "recipients": ["ghost-id"],
        },
    )
    assert response.status_code == 400
    assert "recipient_not_member" in response.json()["detail"]


async def _drain_tasks(server: ChatServer) -> None:
    while server.executor._tasks:
        for task in list(server.executor._tasks.values()):
            try:
                await task
            except Exception:
                pass


async def test_handler_yielded_event_strips_author_from_recipients(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ChatServer(store=store, authenticate=auth, run_timeout_seconds=5)

    @server.assistant("specialist")
    async def specialist(ctx, send):
        yield send.message(
            content=[TextPart(text="self-addressed")],
            recipients=["specialist", "u_alice"],
        )

    app = FastAPI()
    app.state.chat_server = server
    app.include_router(server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    await client.post(
        f"/chat/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "assistant",
                "id": "specialist",
                "name": "Specialist",
                "metadata": {},
            }
        },
    )
    await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "hi"}],
            "recipients": ["specialist"],
        },
    )
    await _drain_tasks(server)

    events = (await client.get(f"/chat/threads/{thread_id}/events")).json()["items"]
    assistant_msgs = [e for e in events if e["type"] == "message" and e["author"]["id"] == "specialist"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["recipients"] == ["u_alice"]


async def test_assistant_to_assistant_chain_auto_invokes(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ChatServer(store=store, authenticate=auth, run_timeout_seconds=5)
    ran_a: list[str] = []
    ran_b: list[str] = []

    @server.assistant("assistant_a")
    async def assistant_a(ctx, send):
        ran_a.append(ctx.run.id)
        yield send.message(
            content=[TextPart(text="A delegating to B")],
            recipients=["assistant_b"],
        )

    @server.assistant("assistant_b")
    async def assistant_b(ctx, send):
        ran_b.append(ctx.run.id)
        yield send.message(content=[TextPart(text="B answering")])

    app = FastAPI()
    app.state.chat_server = server
    app.include_router(server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    for aid, name in [("assistant_a", "A"), ("assistant_b", "B")]:
        await client.post(
            f"/chat/threads/{thread_id}/members",
            json={
                "identity": {
                    "role": "assistant",
                    "id": aid,
                    "name": name,
                    "metadata": {},
                }
            },
        )

    await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "start"}],
            "recipients": ["assistant_a"],
        },
    )
    await _drain_tasks(server)

    assert len(ran_a) == 1
    assert len(ran_b) == 1


async def test_chain_depth_caps_runaway_chain(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ChatServer(store=store, authenticate=auth, run_timeout_seconds=5)
    runs: list[tuple[str, int]] = []

    @server.assistant("a")
    async def a(ctx, send):
        depth = server.executor.chain_depth_for(ctx.run.id)
        runs.append(("a", depth))
        yield send.message(
            content=[TextPart(text="to b")],
            recipients=["b"],
        )

    @server.assistant("b")
    async def b(ctx, send):
        depth = server.executor.chain_depth_for(ctx.run.id)
        runs.append(("b", depth))
        yield send.message(
            content=[TextPart(text="to a")],
            recipients=["a"],
        )

    app = FastAPI()
    app.state.chat_server = server
    app.include_router(server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    for aid, name in [("a", "A"), ("b", "B")]:
        await client.post(
            f"/chat/threads/{thread_id}/members",
            json={
                "identity": {
                    "role": "assistant",
                    "id": aid,
                    "name": name,
                    "metadata": {},
                }
            },
        )

    await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "kick off"}],
            "recipients": ["a"],
        },
    )
    await _drain_tasks(server)

    depths = [d for _, d in runs]
    assert max(depths) <= 8


async def test_authorize_target_id_gates_per_assistant(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    async def authorize(
        identity: Identity,
        thread_id: str,
        action: str,
        *,
        target_id: str | None = None,
    ) -> bool:
        if action == "assistant.invoke":
            return target_id == "allowed"
        return True

    server = ChatServer(
        store=store,
        authenticate=auth,
        authorize=authorize,
        run_timeout_seconds=5,
    )
    ran: list[str] = []

    @server.assistant("allowed")
    async def allowed(ctx, send):
        ran.append("allowed")
        yield send.message(content=[TextPart(text="ok")])

    @server.assistant("denied")
    async def denied(ctx, send):
        ran.append("denied")
        yield send.message(content=[TextPart(text="should not run")])

    app = FastAPI()
    app.state.chat_server = server
    app.include_router(server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    for aid in ["allowed", "denied"]:
        await client.post(
            f"/chat/threads/{thread_id}/members",
            json={
                "identity": {
                    "role": "assistant",
                    "id": aid,
                    "name": aid,
                    "metadata": {},
                }
            },
        )

    await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "ping"}],
            "recipients": ["allowed", "denied"],
        },
    )
    await _drain_tasks(server)

    assert ran == ["allowed"]


async def test_auto_invoke_disabled_preserves_current_behavior(
    clean_db: asyncpg.Pool,
) -> None:
    server, client, thread_id, ran = await _build_env(
        clean_db,
        auto_invoke_recipients=False,
    )

    response = await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "hello"}],
            "recipients": ["specialist"],
        },
    )
    assert response.status_code == 201
    assert response.json()["recipients"] == ["specialist"]

    await asyncio.sleep(0.1)
    for task in list(server.executor._tasks.values()):
        try:
            await task
        except Exception:
            pass

    assert ran == []
