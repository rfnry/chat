import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from rfnry_chat_protocol import Thread, UserIdentity

from rfnry_chat_server.observability import Observability, ObservabilityRecord
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.memory import InMemoryChatStore


class _Capture:
    def __init__(self) -> None:
        self.records: list[ObservabilityRecord] = []

    async def emit(self, record: ObservabilityRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_watchdog_sweep_failure_logs_error() -> None:
    sink = _Capture()
    obs = Observability(sink=sink, level="debug")

    class _BrokenStore(InMemoryChatStore):
        async def find_runs_started_before(self, *, threshold: Any, limit: int) -> Any:
            raise RuntimeError("db down")

    server = ChatServer(
        store=_BrokenStore(),
        observability=obs,
        watchdog_interval_seconds=0.05,
    )
    async with server.running():
        await asyncio.sleep(0.15)
    kinds = [r.kind for r in sink.records]
    assert "watchdog.sweep_failed" in kinds
    sweep_record = next(r for r in sink.records if r.kind == "watchdog.sweep_failed")
    assert sweep_record.level == "error"
    assert sweep_record.error_type == "RuntimeError"
    assert sweep_record.error_message == "db down"


@pytest.mark.asyncio
async def test_run_lifecycle_emits_observability_records() -> None:
    sink = _Capture()
    obs = Observability(sink=sink, level="debug")
    server = ChatServer(store=InMemoryChatStore(), observability=obs)
    user = UserIdentity(id="user_1", name="u")
    now = datetime.now(UTC)
    thread = await server.store.create_thread(
        Thread(
            id="th_1",
            tenant={"org": "acme"},
            metadata={},
            created_at=now,
            updated_at=now,
        )
    )
    run = await server.begin_run(
        thread=thread,
        actor=user,
        triggered_by=user,
        idempotency_key=None,
    )
    await server.end_run(run_id=run.id, error=None)
    kinds = [r.kind for r in sink.records]
    assert "run.begin" in kinds
    assert "run.end" in kinds
    end_record = next(r for r in sink.records if r.kind == "run.end")
    assert end_record.level == "info"
    assert end_record.run_id == run.id
    assert end_record.thread_id == thread.id
