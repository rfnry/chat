from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rfnry_chat_protocol import MessageEvent, TextPart, Thread, UserIdentity

from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.handler.context import HandlerContext
from rfnry_chat_server.handler.send import HandlerSend
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.memory.store import InMemoryChatStore


def _make_server() -> tuple[ChatServer, InMemoryChatStore, RecordingBroadcaster]:
    store = InMemoryChatStore()
    rec = RecordingBroadcaster()
    server = ChatServer(store=store, broadcaster=rec)
    return server, store, rec


async def _make_thread(store: InMemoryChatStore, thread_id: str, alice: UserIdentity) -> Thread:
    now = datetime.now(UTC)
    thread = Thread(id=thread_id, tenant={}, metadata={}, created_at=now, updated_at=now)
    thread = await store.create_thread(thread, caller_identity_id=alice.id)
    await store.add_member(thread.id, alice, added_by=alice)
    return thread


def _user_message(thread_id: str, text: str, evt_id: str = "evt_1") -> MessageEvent:
    return MessageEvent(
        id=evt_id,
        thread_id=thread_id,
        author=UserIdentity(id="u_alice", name="Alice"),
        created_at=datetime.now(UTC),
        content=[TextPart(text=text)],
    )


async def test_early_return_handler_lazy_opens_no_run() -> None:
    """lazy_run=True: a server emitter handler that returns without yielding must
    not produce a phantom run (no run row, no run.started / run.completed)."""
    server, store, rec = _make_server()
    alice = UserIdentity(id="u_alice", name="Alice")
    thread = await _make_thread(store, "th_test1", alice)

    @server.on_message(lazy_run=True)
    async def _noop(_ctx: HandlerContext, _send: HandlerSend):
        # Early-return emitter: never yields anything.
        return
        yield  # pragma: no cover — marks as async-generator

    evt = _user_message(thread.id, "hi")
    await server._handler_dispatcher.dispatch(evt, thread)

    # No run should exist for this thread at all.
    runs = [r for r in store._runs.values() if r.thread_id == thread.id]
    assert runs == [], f"Expected no runs, got: {runs}"

    # No run.started / run.completed events should have been broadcast.
    run_event_types = [e.type for e in rec.events if e.type in ("run.started", "run.completed", "run.failed")]
    assert run_event_types == [], f"Expected no run lifecycle events, got: {run_event_types}"


async def test_early_return_handler_eager_opens_phantom_run_pair() -> None:
    """Default eager mode: a server emitter handler that early-returns without
    yielding still creates a run.started / run.completed pair because begin_run
    fires before the handler body. Handlers with application-level guards must
    opt into lazy_run=True to avoid phantom runs."""
    server, store, rec = _make_server()
    alice = UserIdentity(id="u_alice", name="Alice")
    thread = await _make_thread(store, "th_test1b", alice)

    @server.on_message()  # lazy_run=False (default)
    async def _noop(_ctx: HandlerContext, _send: HandlerSend):
        return
        yield  # pragma: no cover — marks as async-generator

    evt = _user_message(thread.id, "hi")
    await server._handler_dispatcher.dispatch(evt, thread)

    # Eager default: a run is created and immediately completed.
    runs = [r for r in store._runs.values() if r.thread_id == thread.id]
    assert len(runs) == 1, f"Expected 1 phantom run, got: {runs}"
    assert runs[0].status == "completed"

    run_event_types = [e.type for e in rec.events if e.type in ("run.started", "run.completed", "run.failed")]
    assert run_event_types == ["run.started", "run.completed"], f"Got: {run_event_types}"


async def test_yielding_handler_opens_exactly_one_run() -> None:
    """A handler that yields must open exactly one run and close it as
    completed. Emitted events must carry the run_id."""
    server, store, rec = _make_server()
    alice = UserIdentity(id="u_alice", name="Alice")
    thread = await _make_thread(store, "th_test2", alice)

    @server.on_message()
    async def _echo(_ctx: HandlerContext, send: HandlerSend):
        yield send.message(content=[TextPart(text="ack")])

    evt = _user_message(thread.id, "hi")
    await server._handler_dispatcher.dispatch(evt, thread)

    runs = [r for r in store._runs.values() if r.thread_id == thread.id]
    assert len(runs) == 1, f"Expected exactly 1 run, got: {runs}"
    assert runs[0].status == "completed"

    # The emitted message event must carry the run_id.
    messages = [e for e in rec.events if e.type == "message" and e.author.role == "system"]
    assert len(messages) == 1
    assert messages[0].run_id == runs[0].id


async def test_exception_before_first_yield_eager_fails_run() -> None:
    """Default eager mode: an emitter handler that raises before ever yielding
    still has the run open (eager begin_run fired before the body), so the run
    transitions to failed with handler_error."""
    server, store, rec = _make_server()
    alice = UserIdentity(id="u_alice", name="Alice")
    thread = await _make_thread(store, "th_test3", alice)

    @server.on_message()  # lazy_run=False (default)
    async def _explode(_ctx: HandlerContext, _send: HandlerSend):
        raise RuntimeError("boom before yield")
        yield  # pragma: no cover

    evt = _user_message(thread.id, "hi")

    with pytest.raises(RuntimeError, match="boom before yield"):
        await server._handler_dispatcher.dispatch(evt, thread)

    runs = [r for r in store._runs.values() if r.thread_id == thread.id]
    assert len(runs) == 1, f"Expected 1 failed run, got: {runs}"
    assert runs[0].status == "failed"
    assert runs[0].error is not None
    assert runs[0].error.code == "handler_error"


async def test_exception_before_first_yield_lazy_opens_no_run() -> None:
    """lazy_run=True: an emitter handler that raises before ever yielding must
    not open a run (begin_run deferred to first yield — no phantom run.failed)."""
    server, store, rec = _make_server()
    alice = UserIdentity(id="u_alice", name="Alice")
    thread = await _make_thread(store, "th_test3b", alice)

    @server.on_message(lazy_run=True)
    async def _explode(_ctx: HandlerContext, _send: HandlerSend):
        raise RuntimeError("boom before yield")
        yield  # pragma: no cover

    evt = _user_message(thread.id, "hi")

    with pytest.raises(RuntimeError, match="boom before yield"):
        await server._handler_dispatcher.dispatch(evt, thread)

    runs = [r for r in store._runs.values() if r.thread_id == thread.id]
    assert runs == [], f"Expected no runs after pre-yield exception with lazy_run=True, got: {runs}"

    run_event_types = [e.type for e in rec.events if e.type in ("run.started", "run.completed", "run.failed")]
    assert run_event_types == [], f"Expected no run lifecycle events, got: {run_event_types}"


async def test_exception_after_yield_fails_run() -> None:
    """An emitter handler that yields once then raises must end the run
    as failed, not leave it orphaned."""
    server, store, rec = _make_server()
    alice = UserIdentity(id="u_alice", name="Alice")
    thread = await _make_thread(store, "th_test4", alice)

    @server.on_message()
    async def _yield_then_explode(_ctx: HandlerContext, send: HandlerSend):
        yield send.message(content=[TextPart(text="first")])
        raise RuntimeError("boom after yield")

    evt = _user_message(thread.id, "hi")

    with pytest.raises(RuntimeError, match="boom after yield"):
        await server._handler_dispatcher.dispatch(evt, thread)

    runs = [r for r in store._runs.values() if r.thread_id == thread.id]
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].error is not None
    assert runs[0].error.code == "handler_error"


async def test_multiple_yields_single_run() -> None:
    """A handler that yields multiple times must still open exactly one
    run (not one per yield)."""
    server, store, rec = _make_server()
    alice = UserIdentity(id="u_alice", name="Alice")
    thread = await _make_thread(store, "th_test5", alice)

    @server.on_message()
    async def _multi(_ctx: HandlerContext, send: HandlerSend):
        yield send.message(content=[TextPart(text="one")])
        yield send.message(content=[TextPart(text="two")])
        yield send.message(content=[TextPart(text="three")])

    evt = _user_message(thread.id, "hi")
    await server._handler_dispatcher.dispatch(evt, thread)

    runs = [r for r in store._runs.values() if r.thread_id == thread.id]
    assert len(runs) == 1
    assert runs[0].status == "completed"

    messages = [e for e in rec.events if e.type == "message" and e.author.role == "system"]
    assert len(messages) == 3
    # All three messages must carry the same run_id.
    assert all(m.run_id == runs[0].id for m in messages)


async def test_eager_run_started_event_precedes_first_emitted_message() -> None:
    """Default eager mode: run.started is broadcast before the handler body
    runs, so it appears in the event log before any yielded message event —
    even when the handler has an internal await before its first yield."""
    import asyncio

    server, store, rec = _make_server()
    alice = UserIdentity(id="u_alice", name="Alice")
    thread = await _make_thread(store, "th_test6", alice)

    @server.on_message()  # lazy_run=False (default)
    async def _delayed(_ctx: HandlerContext, send: HandlerSend):
        # Simulate async work (e.g. LLM call) before yielding.
        await asyncio.sleep(0)
        yield send.message(content=[TextPart(text="response")])

    evt = _user_message(thread.id, "hi")
    await server._handler_dispatcher.dispatch(evt, thread)

    # Extract just the event types for clarity.
    types = [e.type for e in rec.events]

    # run.started must appear before the first message event.
    assert "run.started" in types
    assert "message" in types
    run_started_idx = next(i for i, t in enumerate(types) if t == "run.started")
    first_message_idx = next(i for i, t in enumerate(types) if t == "message")
    assert run_started_idx < first_message_idx, (
        f"Expected run.started before message; got order: {types}"
    )
