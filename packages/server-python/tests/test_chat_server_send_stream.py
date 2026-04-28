from __future__ import annotations

import asyncpg
from rfnry_chat_protocol import AssistantIdentity, Identity, MessageEvent, ReasoningEvent, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


async def _setup(clean_db: asyncpg.Pool) -> tuple[ChatServer, str, AssistantIdentity]:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    gateway = AssistantIdentity(
        id="gateway",
        name="Gateway",
        metadata={"tenant": {"org": "A"}},
    )

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ChatServer(store=store, authenticate=auth)

    from datetime import UTC, datetime

    from rfnry_chat_protocol import Thread

    t = Thread(
        id="th_send_stream",
        tenant={"org": "A"},
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    thread = await store.create_thread(t, caller_identity_id=alice.id, client_id=None)
    await store.add_member(thread.id, alice, added_by=alice)
    await store.add_member(thread.id, gateway, added_by=alice)
    return server, thread.id, gateway


async def test_chat_server_send_message_stream_persists_finalized_message(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _setup(clean_db)
    async with server.send(thread_id, as_identity=gateway) as send:
        async with send.message_stream() as stream:
            await stream.write("hello ")
            await stream.write("world")

    page = await server.store.list_events(thread_id, limit=50)
    msgs = [e for e in page.items if e.type == "message" and isinstance(e, MessageEvent)]
    assert any(any(p.type == "text" and p.text == "hello world" for p in m.content) for m in msgs)


async def test_chat_server_send_reasoning_stream_persists_reasoning(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _setup(clean_db)
    async with server.send(thread_id, as_identity=gateway) as send:
        async with send.reasoning_stream() as stream:
            await stream.write("thinking…")

    page = await server.store.list_events(thread_id, limit=50)
    reasonings = [e for e in page.items if e.type == "reasoning" and isinstance(e, ReasoningEvent)]
    assert any(r.content == "thinking…" for r in reasonings)


async def test_chat_server_send_stream_recipients_propagate(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _setup(clean_db)
    async with server.send(thread_id, as_identity=gateway) as send:
        async with send.message_stream(recipients=["u_alice"]) as stream:
            await stream.write("for alice only")

    page = await server.store.list_events(thread_id, limit=50)
    final = next(
        e
        for e in page.items
        if e.type == "message"
        and isinstance(e, MessageEvent)
        and any(p.type == "text" and p.text == "for alice only" for p in e.content)
    )
    assert final.recipients == ["u_alice"]


async def test_chat_server_send_stream_run_id_propagates(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _setup(clean_db)
    captured_run_id: list[str] = []
    async with server.send(thread_id, as_identity=gateway) as send:
        captured_run_id.append(send.run_id or "")
        async with send.message_stream() as stream:
            await stream.write("x")

    page = await server.store.list_events(thread_id, limit=50)
    final = next(
        e
        for e in page.items
        if e.type == "message"
        and isinstance(e, MessageEvent)
        and any(p.type == "text" and p.text == "x" for p in e.content)
    )
    assert final.run_id == captured_run_id[0]
