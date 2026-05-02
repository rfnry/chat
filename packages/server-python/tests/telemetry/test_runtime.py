from datetime import UTC, datetime

import pytest

from rfnry_chat_server.telemetry.record import TelemetryRow
from rfnry_chat_server.telemetry.runtime import Telemetry


class _Capture:
    def __init__(self) -> None:
        self.rows: list[TelemetryRow] = []

    async def write(self, row: TelemetryRow) -> None:
        self.rows.append(row)


def _row() -> TelemetryRow:
    return TelemetryRow(
        at=datetime.now(UTC),
        scope_leaf="default",
        thread_id="thr_1",
        run_id="run_1",
        actor_kind="user",
        actor_id="u",
        worker_id="u",
        triggered_by_id="u",
        status="completed",
    )


@pytest.mark.asyncio
async def test_record_run_writes_row() -> None:
    sink = _Capture()
    tel = Telemetry(sink=sink)
    await tel.record_run(_row())
    assert len(sink.rows) == 1


@pytest.mark.asyncio
async def test_record_run_suppresses_sink_failure() -> None:
    class _Broken:
        async def write(self, row: TelemetryRow) -> None:
            raise RuntimeError("nope")

    tel = Telemetry(sink=_Broken())
    await tel.record_run(_row())
