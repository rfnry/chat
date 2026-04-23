"""Tests for ChatServer.end_run idempotency.

`end_run` used to re-update the run row and re-publish `run.completed` /
`run.failed` even when the run was already terminal. Double-ends (e.g.
watchdog timeout racing normal completion, or a handler that re-ends on its
own error path) produced duplicate frames. The fix short-circuits when the
run is already terminal so callers can safely call end_run twice.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rfnry_chat_protocol import (
    AssistantIdentity,
    RunError,
    Thread,
    UserIdentity,
)

from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.memory.store import InMemoryChatStore


async def _setup() -> tuple[ChatServer, RecordingBroadcaster, Thread]:
    store = InMemoryChatStore()
    rec = RecordingBroadcaster()
    server = ChatServer(store=store, broadcaster=rec)
    now = datetime.now(UTC)
    thread = await store.create_thread(
        Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now)
    )
    return server, rec, thread


async def test_end_run_is_idempotent_on_completed() -> None:
    """Double-calling end_run on an already-completed run must not publish
    a second run.completed event, and must return the existing terminal run."""
    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    run = await server.begin_run(
        thread=thread, actor=actor, triggered_by=user, idempotency_key=None
    )

    first_end = await server.end_run(run_id=run.id, error=None)
    second_end = await server.end_run(run_id=run.id, error=None)

    assert first_end.status == "completed"
    assert second_end.status == "completed"
    # Run.completed_at should be identical — we did not re-update the row.
    assert first_end.completed_at == second_end.completed_at

    completed = [e for e in rec.events if e.type == "run.completed"]
    assert len(completed) == 1


async def test_end_run_is_idempotent_on_failed() -> None:
    """A failed run can be re-ended without publishing a second run.failed."""
    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    run = await server.begin_run(
        thread=thread, actor=actor, triggered_by=user, idempotency_key=None
    )

    err = RunError(code="handler_error", message="boom")
    await server.end_run(run_id=run.id, error=err)
    # Second call — even with a different error — is a no-op.
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
    """cancel_run transitions to a terminal state; a subsequent end_run must
    not re-terminate the run or publish another frame."""
    server, rec, thread = await _setup()
    actor = AssistantIdentity(id="a_1", name="Bot")
    user = UserIdentity(id="u_1", name="Alice")

    run = await server.begin_run(
        thread=thread, actor=actor, triggered_by=user, idempotency_key=None
    )
    await server.cancel_run(run_id=run.id)

    # end_run on an already-cancelled run returns the existing run and does
    # not publish a run.completed / run.failed frame.
    result = await server.end_run(run_id=run.id, error=None)
    assert result.status == "cancelled"

    completed = [e for e in rec.events if e.type == "run.completed"]
    failed = [e for e in rec.events if e.type == "run.failed"]
    cancelled = [e for e in rec.events if e.type == "run.cancelled"]
    assert completed == []
    assert failed == []
    assert len(cancelled) == 1
