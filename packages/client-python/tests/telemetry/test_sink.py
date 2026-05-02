import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rfnry_chat_client.telemetry.record import TelemetryRow
from rfnry_chat_client.telemetry.sink import (
    JsonlTelemetrySink,
    MultiTelemetrySink,
    NullTelemetrySink,
    SqliteTelemetrySink,
)


def _row(**overrides: object) -> TelemetryRow:
    base: dict[str, object] = dict(
        at=datetime.now(UTC),
        scope_leaf="acme/u1",
        thread_id="thr_1",
        run_id="run_1",
        actor_kind="user",
        actor_id="user_1",
        worker_id="user_1",
        triggered_by_id="user_1",
        status="completed",
    )
    base.update(overrides)
    return TelemetryRow(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_sqlite_sink_creates_table_and_inserts(tmp_path: Path) -> None:
    sink = SqliteTelemetrySink(agent_root=tmp_path)
    await sink.write(_row(events_emitted=3, tool_calls=1, duration_ms=42))
    db_path = tmp_path / "data" / "acme/u1" / "state.db"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT scope_leaf, thread_id, run_id, events_emitted, duration_ms FROM telemetry"
    ).fetchall()
    assert rows == [("acme/u1", "thr_1", "run_1", 3, 42)]
    conn.close()


@pytest.mark.asyncio
async def test_sqlite_sink_uses_data_root_override(tmp_path: Path) -> None:
    data = tmp_path / "elsewhere"
    sink = SqliteTelemetrySink(agent_root=tmp_path, data_root=data)
    await sink.write(_row())
    assert (data / "acme/u1" / "state.db").exists()


@pytest.mark.asyncio
async def test_sqlite_sink_idempotent_replace(tmp_path: Path) -> None:
    sink = SqliteTelemetrySink(agent_root=tmp_path)
    await sink.write(_row(events_emitted=1))
    await sink.write(_row(events_emitted=99))
    db_path = tmp_path / "data" / "acme/u1" / "state.db"
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT events_emitted FROM telemetry").fetchall()
    assert rows == [(99,)]
    conn.close()


@pytest.mark.asyncio
async def test_jsonl_telemetry_sink_appends(tmp_path: Path) -> None:
    target = tmp_path / "telemetry.jsonl"
    sink = JsonlTelemetrySink(path=target)
    await sink.write(_row(events_emitted=2))
    await sink.write(_row(run_id="run_2", events_emitted=5))
    lines = target.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["run_id"] == "run_2"


@pytest.mark.asyncio
async def test_multi_telemetry_sink_isolates_failure() -> None:
    captured: list[TelemetryRow] = []

    class _Capture:
        async def write(self, row: TelemetryRow) -> None:
            captured.append(row)

    class _Broken:
        async def write(self, row: TelemetryRow) -> None:
            raise RuntimeError("broken")

    multi = MultiTelemetrySink(sinks=[_Broken(), _Capture()])
    await multi.write(_row())
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_null_telemetry_sink_silences() -> None:
    await NullTelemetrySink().write(_row())
