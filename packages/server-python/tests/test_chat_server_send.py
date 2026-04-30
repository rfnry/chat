from __future__ import annotations

import asyncpg
import pytest
from rfnry_chat_protocol import AssistantIdentity, Identity, TextPart, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.send import Send
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


async def _make_server_with_thread(clean_db: asyncpg.Pool) -> tuple[ChatServer, str, AssistantIdentity]:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    gateway = AssistantIdentity(
        id="gateway_whatsapp",
        name="WhatsApp Gateway",
        metadata={"tenant": {"org": "A"}},
    )

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ChatServer(store=store, authenticate=auth)
    thread = (
        await store.create_thread_with_member(
            tenant={"org": "A"},
            creator=alice,
        )
        if hasattr(store, "create_thread_with_member")
        else None
    )
    if thread is None:
        from datetime import UTC, datetime

        from rfnry_chat_protocol import Thread

        t = Thread(
            id="th_test_send",
            tenant={"org": "A"},
            metadata={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        thread = await store.create_thread(t, caller_identity_id=alice.id, client_id=None)
        await store.add_member(thread.id, alice, added_by=alice)
        await store.add_member(thread.id, gateway, added_by=alice)
    return server, thread.id, gateway


async def test_server_send_yields_send_authored_as_identity(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    async with server.send(thread_id, as_identity=gateway) as send:
        assert isinstance(send, Send)
        evt = send.message([TextPart(text="hello")])
        assert evt.thread_id == thread_id
        assert evt.author.id == gateway.id


async def test_server_send_persists_emitted_events_under_run(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    async with server.send(thread_id, as_identity=gateway) as send:
        evt = send.message([TextPart(text="from gateway")])
        await server.publish_event(evt)
    page = await server.store.list_events(thread_id, limit=50)
    persisted = [e for e in page.items if e.type == "message" and getattr(e, "content", None)]
    msg = next((e for e in persisted if any(p.type == "text" and p.text == "from gateway" for p in e.content)), None)
    assert msg is not None
    assert msg.author.id == gateway.id
    assert msg.run_id is not None


async def test_server_send_closes_run_on_clean_exit(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    captured_run_id: list[str] = []
    async with server.send(thread_id, as_identity=gateway) as send:
        captured_run_id.append(send.run_id or "")
    run = await server.store.get_run(captured_run_id[0])
    assert run is not None
    assert run.status == "completed"


async def test_server_send_closes_run_with_error_on_exception(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    captured_run_id: list[str] = []
    with pytest.raises(RuntimeError, match="boom"):
        async with server.send(thread_id, as_identity=gateway) as send:
            captured_run_id.append(send.run_id or "")
            raise RuntimeError("boom")
    run = await server.store.get_run(captured_run_id[0])
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None
    assert run.error.code == "send_error"


async def test_server_send_rejects_unknown_thread(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    gateway = AssistantIdentity(id="g_x", name="Gateway")

    async def auth(_h: HandshakeData) -> Identity:
        return gateway

    server = ChatServer(store=store, authenticate=auth)
    with pytest.raises(LookupError):
        async with server.send("th_does_not_exist", as_identity=gateway) as _:
            pass


async def test_server_send_rejects_unauthorized_identity(clean_db: asyncpg.Pool) -> None:
    server, thread_id, _gateway = await _make_server_with_thread(clean_db)
    outsider = AssistantIdentity(id="not_a_member", name="Outsider", metadata={"tenant": {"org": "A"}})
    with pytest.raises(PermissionError):
        async with server.send(thread_id, as_identity=outsider) as _:
            pass


async def test_server_send_supports_multiple_emissions(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    async with server.send(thread_id, as_identity=gateway) as send:
        await server.publish_event(send.message([TextPart(text="one")]))
        await server.publish_event(send.message([TextPart(text="two")]))
    page = await server.store.list_events(thread_id, limit=50)
    bodies = [p.text for e in page.items if e.type == "message" for p in e.content if p.type == "text"]
    assert "one" in bodies
    assert "two" in bodies


async def test_server_send_emit_method_persists_through_publish_event(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    async with server.send(thread_id, as_identity=gateway) as send:
        await send.emit(send.message([TextPart(text="via send.emit")]))
    page = await server.store.list_events(thread_id, limit=50)
    bodies = [p.text for e in page.items if e.type == "message" for p in e.content if p.type == "text"]
    assert "via send.emit" in bodies


async def test_server_send_lazy_skips_run_open_if_no_emission(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    page_before = await server.store.list_events(thread_id, limit=50)
    runs_before = sum(1 for e in page_before.items if e.type == "run.started")

    async with server.send(thread_id, as_identity=gateway, lazy=True) as _:
        pass

    page_after = await server.store.list_events(thread_id, limit=50)
    runs_after = sum(1 for e in page_after.items if e.type == "run.started")
    assert runs_before == runs_after


async def test_server_send_lazy_opens_run_on_first_emit(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    async with server.send(thread_id, as_identity=gateway, lazy=True) as send:
        await send.emit(send.message([TextPart(text="late")]))
    page = await server.store.list_events(thread_id, limit=50)
    bodies = [p.text for e in page.items if e.type == "message" for p in e.content if p.type == "text"]
    assert "late" in bodies


async def test_server_send_triggered_by_event_extracts_author_identity(clean_db: asyncpg.Pool) -> None:
    from datetime import UTC, datetime

    from rfnry_chat_protocol import MessageEvent

    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    members = await server.store.list_members(thread_id)
    alice = next(m.identity for m in members if m.identity.id == "u_alice")

    captured_run_id: list[str] = []
    triggering = MessageEvent(
        id="evt_origin",
        thread_id=thread_id,
        author=alice,
        created_at=datetime.now(UTC),
        content=[TextPart(text="triggered")],
    )
    async with server.send(thread_id, as_identity=gateway, triggered_by=triggering) as send:
        captured_run_id.append(send.run_id or "")
        await send.emit(send.message([TextPart(text="reply")]))
    run = await server.store.get_run(captured_run_id[0])
    assert run is not None
    assert run.triggered_by.id == "u_alice"


async def test_server_send_triggered_by_identity_used_directly(clean_db: asyncpg.Pool) -> None:
    server, thread_id, gateway = await _make_server_with_thread(clean_db)
    members = await server.store.list_members(thread_id)
    alice = next(m.identity for m in members if m.identity.id == "u_alice")

    captured_run_id: list[str] = []
    async with server.send(thread_id, as_identity=gateway, triggered_by=alice) as send:
        captured_run_id.append(send.run_id or "")
        await send.emit(send.message([TextPart(text="reply")]))
    run = await server.store.get_run(captured_run_id[0])
    assert run is not None
    assert run.triggered_by.id == "u_alice"
