from __future__ import annotations

from datetime import UTC, datetime

from rfnry_chat_protocol import (
    AssistantIdentity,
    RunError,
    Thread,
    UserIdentity,
)

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


async def test_end_run_is_idempotent_on_completed() -> None:

    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    run = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key=None)

    first_end = await server.end_run(run_id=run.id, error=None)
    second_end = await server.end_run(run_id=run.id, error=None)

    assert first_end.status == "completed"
    assert second_end.status == "completed"

    assert first_end.completed_at == second_end.completed_at

    completed = [e for e in rec.events if e.type == "run.completed"]
    assert len(completed) == 1


async def test_end_run_is_idempotent_on_failed() -> None:

    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    run = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key=None)

    err = RunError(code="handler_error", message="boom")
    await server.end_run(run_id=run.id, error=err)

    await server.end_run(run_id=run.id, error=RunError(code="other", message="ignored"))

    failed = [e for e in rec.events if e.type == "run.failed"]
    assert len(failed) == 1
    assert failed[0].error.code == "handler_error"

    refreshed = await server.store.get_run(run.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.error is not None
    assert refreshed.error.code == "handler_error"


async def test_end_run_is_idempotent_on_cancelled() -> None:

    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    run = await server.begin_run(thread=thread, actor=actor, triggered_by=user, idempotency_key=None)
    await server.cancel_run(run_id=run.id)

    result = await server.end_run(run_id=run.id, error=None)
    assert result.status == "cancelled"

    completed = [e for e in rec.events if e.type == "run.completed"]
    failed = [e for e in rec.events if e.type == "run.failed"]
    cancelled = [e for e in rec.events if e.type == "run.cancelled"]
    assert completed == []
    assert failed == []
    assert len(cancelled) == 1


async def test_end_run_raises_for_missing_run() -> None:

    server, _, _ = await _setup()
    try:
        await server.end_run(run_id="run_nonexistent", error=None)
        assert False, "expected LookupError"
    except LookupError as exc:
        assert "run_nonexistent" in str(exc)


async def test_cancel_run_raises_for_missing_run() -> None:

    server, _, _ = await _setup()
    try:
        await server.cancel_run(run_id="run_nonexistent")
        assert False, "expected LookupError"
    except LookupError as exc:
        assert "run_nonexistent" in str(exc)
