import pytest
from rfnry_chat_protocol import RunError, UserIdentity

from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.memory import InMemoryChatStore
from rfnry_chat_server.telemetry import Telemetry, TelemetryRow


class _Capture:
    def __init__(self) -> None:
        self.rows: list[TelemetryRow] = []

    async def write(self, row: TelemetryRow) -> None:
        self.rows.append(row)


@pytest.mark.asyncio
async def test_one_telemetry_row_per_run_on_completion() -> None:
    sink = _Capture()
    server = ChatServer(store=InMemoryChatStore(), telemetry=Telemetry(sink=sink))
    user = UserIdentity(id="u", name="u")
    thread = await _create_thread(server, user)
    run = await server.begin_run(thread=thread, actor=user, triggered_by=user, idempotency_key=None)
    await server.end_run(run_id=run.id, error=None)
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row.run_id == run.id
    assert row.thread_id == thread.id
    assert row.status == "completed"
    assert row.actor_kind == "user"
    assert row.actor_id == "u"
    assert row.worker_id == "u"
    assert row.triggered_by_id == "u"
    assert row.duration_ms >= 0


@pytest.mark.asyncio
async def test_telemetry_row_records_failure_status_and_error() -> None:
    sink = _Capture()
    server = ChatServer(store=InMemoryChatStore(), telemetry=Telemetry(sink=sink))
    user = UserIdentity(id="u", name="u")
    thread = await _create_thread(server, user)
    run = await server.begin_run(thread=thread, actor=user, triggered_by=user, idempotency_key=None)
    await server.end_run(run_id=run.id, error=RunError(code="handler_error", message="boom"))
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row.status == "failed"
    assert row.error_code == "handler_error"
    assert row.error_message == "boom"


@pytest.mark.asyncio
async def test_accumulator_drains_when_thread_deleted_between_begin_and_end() -> None:
    sink = _Capture()
    server = ChatServer(store=InMemoryChatStore(), telemetry=Telemetry(sink=sink))
    user = UserIdentity(id="u", name="u")
    thread = await _create_thread(server, user)
    run = await server.begin_run(thread=thread, actor=user, triggered_by=user, idempotency_key=None)
    assert run.id in server._run_accum  # accumulator populated

    # Simulate the thread vanishing between begin_run and end_run (e.g. another worker
    # deleted it). Pop the thread row directly so the run row remains and end_run can
    # still locate the run via update_run_status_if_active — exercising the
    # "thread is None" branch of end_run that previously leaked the accumulator.
    server.store._threads.pop(thread.id, None)

    # end_run still drains the accumulator even though no row is written (no thread)
    await server.end_run(run_id=run.id, error=None)
    assert run.id not in server._run_accum
    assert len(sink.rows) == 0  # no row written because thread was gone


@pytest.mark.asyncio
async def test_accumulator_drains_when_run_lookup_fails() -> None:
    sink = _Capture()
    server = ChatServer(store=InMemoryChatStore(), telemetry=Telemetry(sink=sink))
    user = UserIdentity(id="u", name="u")
    thread = await _create_thread(server, user)
    run = await server.begin_run(thread=thread, actor=user, triggered_by=user, idempotency_key=None)
    assert run.id in server._run_accum

    # Cascade-delete the thread (also deletes the run from the store)
    await server.store.delete_thread(thread.id)

    # end_run will raise LookupError because the run no longer exists in the store.
    # The accumulator entry must still be drained.
    with pytest.raises(LookupError):
        await server.end_run(run_id=run.id, error=None)
    assert run.id not in server._run_accum
    assert len(sink.rows) == 0


@pytest.mark.asyncio
async def test_run_counters_accumulate_events_emitted() -> None:
    from datetime import UTC, datetime

    from rfnry_chat_protocol import (
        MessageEvent,
        StreamDeltaFrame,
        StreamEndFrame,
        StreamStartFrame,
        TextPart,
        ToolCall,
        ToolCallEvent,
        ToolResult,
        ToolResultEvent,
    )

    from rfnry_chat_server.broadcast.recording import RecordingBroadcaster

    sink = _Capture()
    server = ChatServer(
        store=InMemoryChatStore(),
        telemetry=Telemetry(sink=sink),
        broadcaster=RecordingBroadcaster(),
    )
    user = UserIdentity(id="u", name="u")
    thread = await _create_thread(server, user)
    run = await server.begin_run(thread=thread, actor=user, triggered_by=user, idempotency_key=None)

    # plain message event — increments events_emitted only
    msg = MessageEvent(
        id="evt_1",
        thread_id=thread.id,
        author=user,
        content=[TextPart(text="hi")],
        run_id=run.id,
        created_at=datetime.now(UTC),
    )
    await server.publish_event(msg, thread=thread)

    # tool.call event — increments events_emitted AND tool_calls
    tc = ToolCallEvent(
        id="evt_2",
        thread_id=thread.id,
        author=user,
        run_id=run.id,
        created_at=datetime.now(UTC),
        tool=ToolCall(id="t_1", name="get_stock", arguments={}),
    )
    await server.publish_event(tc, thread=thread)

    # tool.result event with no error — increments events_emitted only
    tr_ok = ToolResultEvent(
        id="evt_3",
        thread_id=thread.id,
        author=user,
        run_id=run.id,
        created_at=datetime.now(UTC),
        tool=ToolResult(id="t_1", result={"ok": True}),
    )
    await server.publish_event(tr_ok, thread=thread)

    # tool.result event with error — increments events_emitted AND tool_errors
    tr_err = ToolResultEvent(
        id="evt_4",
        thread_id=thread.id,
        author=user,
        run_id=run.id,
        created_at=datetime.now(UTC),
        tool=ToolResult(id="t_2", error={"code": "boom", "message": "x"}),
    )
    await server.publish_event(tr_err, thread=thread)

    # event with no run_id — must not increment any counter, must not crash
    msg_norun = MessageEvent(
        id="evt_5",
        thread_id=thread.id,
        author=user,
        content=[TextPart(text="bare")],
        created_at=datetime.now(UTC),
    )
    await server.publish_event(msg_norun, thread=thread)

    # stream deltas — start frame registers run_id, deltas increment counter
    start = StreamStartFrame(
        event_id="strm_1",
        thread_id=thread.id,
        run_id=run.id,
        target_type="message",
        author=user,
    )
    await server.broadcast_stream_start(start, thread=thread)
    for i in range(3):
        await server.broadcast_stream_delta(
            StreamDeltaFrame(event_id="strm_1", thread_id=thread.id, text=f"chunk{i}"),
            thread=thread,
        )
    await server.broadcast_stream_end(
        StreamEndFrame(event_id="strm_1", thread_id=thread.id),
        thread=thread,
    )

    # delta with unknown event_id — must not crash, must not increment
    await server.broadcast_stream_delta(
        StreamDeltaFrame(event_id="strm_unknown", thread_id=thread.id, text="x"),
        thread=thread,
    )

    await server.end_run(run_id=run.id, error=None)

    row = sink.rows[0]
    # events_emitted counts: msg + tool.call + tool.result(ok) + tool.result(err) = 4
    # plus run.started + run.completed which carry run_id and are published by the server itself
    assert row.events_emitted >= 4
    assert row.tool_calls == 1
    assert row.tool_errors == 1
    assert row.stream_deltas == 3


@pytest.mark.asyncio
async def test_watchdog_timeout_emits_row_with_failed_status() -> None:
    import asyncio

    sink = _Capture()
    server = ChatServer(
        store=InMemoryChatStore(),
        telemetry=Telemetry(sink=sink),
        run_timeout_seconds=0,
        watchdog_interval_seconds=0.05,
    )
    user = UserIdentity(id="u", name="u")
    thread = await _create_thread(server, user)
    async with server.running():
        await server.begin_run(thread=thread, actor=user, triggered_by=user, idempotency_key=None)
        # Wait for the watchdog to time it out
        await asyncio.sleep(0.2)
    statuses = [r.status for r in sink.rows]
    assert "failed" in statuses
    timed_out = next(r for r in sink.rows if r.status == "failed")
    assert timed_out.error_code == "timeout"
    assert timed_out.error_message  # non-empty timeout message


async def _create_thread(server: ChatServer, identity: UserIdentity):
    """Helper that calls store.create_thread with whatever signature this version uses.

    Inspect existing test files (e.g. test_chat_server_begin_run.py, test_observability_swallows.py)
    to confirm the construction pattern. The InMemoryChatStore.create_thread signature accepts a
    Thread instance positionally — see existing tests for the exact construction.
    """
    from datetime import UTC, datetime

    from rfnry_chat_protocol import Thread

    thread = Thread(
        id="thr_x",
        tenant={"org": "acme"},
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return await server.store.create_thread(thread)
