import asyncio
from typing import Any

import pytest

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
