from __future__ import annotations

from datetime import UTC, datetime

from rfnry_chat_protocol import AssistantIdentity, Thread, UserIdentity

from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.memory.store import InMemoryChatStore


async def _setup() -> tuple[ChatServer, RecordingBroadcaster, Thread]:
    store = InMemoryChatStore()
    rec = RecordingBroadcaster()
    server = ChatServer(store=store, broadcaster=rec)
    now = datetime.now(UTC)
    thread = await store.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    return server, rec, thread


async def test_begin_run_creates_distinct_runs_for_same_actor() -> None:

    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    first = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key=None)

    await server.end_run(run_id=first.id, error=None)

    second = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key=None)
    await server.end_run(run_id=second.id, error=None)

    assert first.id != second.id
    started_ids = [e.run_id for e in rec.events if e.type == "run.started"]
    assert started_ids == [first.id, second.id]


async def test_begin_run_reuses_via_idempotency_key() -> None:

    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    first = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key="key-a")
    second = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key="key-a")

    assert first.id == second.id
    started = [e for e in rec.events if e.type == "run.started"]
    assert len(started) == 1
