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
