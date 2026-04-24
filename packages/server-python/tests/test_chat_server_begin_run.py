"""Tests for ChatServer.begin_run reuse semantics.

Previously `begin_run` silently returned any existing active run for the
same (thread, actor) pair, discovered via `find_active_run`. That implicit
reuse violated the caller's mental model and produced phantom run.started
fan-out in multi-agent channels. The fix removes the implicit reuse path;
the only supported reuse mechanism is the explicit `idempotency_key`.
"""

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
    """Two begin_run calls with no idempotency_key produce two distinct runs
    and two run.started events — even for the same (thread, actor)."""
    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    first = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key=None)
    # End the first run before starting the second, so we do not rely on
    # concurrent-active semantics (the Postgres store enforces a partial
    # unique index that would reject two simultaneous active runs for the
    # same actor; that concurrency constraint is separate from this contract).
    await server.end_run(run_id=first.id, error=None)

    second = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key=None)
    await server.end_run(run_id=second.id, error=None)

    assert first.id != second.id
    started_ids = [e.run_id for e in rec.events if e.type == "run.started"]
    assert started_ids == [first.id, second.id]


async def test_begin_run_reuses_via_idempotency_key() -> None:
    """Explicit reuse still works through idempotency_key — the ONLY
    supported reuse path after the fix."""
    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    first = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key="key-a")
    second = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key="key-a")

    assert first.id == second.id
    started = [e for e in rec.events if e.type == "run.started"]
    assert len(started) == 1
