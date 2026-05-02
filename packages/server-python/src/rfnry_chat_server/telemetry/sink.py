from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, PrivateAttr

from rfnry_chat_server.telemetry.record import TelemetryRow


@runtime_checkable
class TelemetrySink(Protocol):
    async def write(self, row: TelemetryRow) -> None: ...


_TELEMETRY_DDL = """
CREATE TABLE IF NOT EXISTS telemetry (
    schema_version INTEGER NOT NULL,
    at TEXT NOT NULL,
    scope_leaf TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    triggered_by_id TEXT NOT NULL,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    stop_reason TEXT,
    error_code TEXT,
    error_message TEXT,
    provider TEXT,
    model TEXT,
    tokens_input INTEGER NOT NULL,
    tokens_output INTEGER NOT NULL,
    tokens_cache_creation INTEGER NOT NULL,
    tokens_cache_read INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    events_emitted INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    tool_errors INTEGER NOT NULL,
    stream_deltas INTEGER NOT NULL,
    PRIMARY KEY (scope_leaf, thread_id, run_id)
)
"""

_TELEMETRY_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_telemetry_scope_at ON telemetry(scope_leaf, at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_telemetry_worker_at ON telemetry(scope_leaf, worker_id, at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_telemetry_status ON telemetry(scope_leaf, status, at DESC)",
)


class SqliteTelemetrySink(BaseModel):
    agent_root: Path
    data_root: Path | None = None

    model_config = {"arbitrary_types_allowed": True}

    _initialized: set[str] = PrivateAttr(default_factory=set)
    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

    def _db_path(self, scope_leaf: str) -> Path:
        base = self.data_root if self.data_root is not None else self.agent_root / "data"
        return base / scope_leaf / "state.db"

    async def write(self, row: TelemetryRow) -> None:
        path = self._db_path(row.scope_leaf)
        async with self._lock:
            await asyncio.to_thread(self._write_sync, path, row)

    def _write_sync(self, path: Path, row: TelemetryRow) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            if str(path) not in self._initialized:
                conn.execute(_TELEMETRY_DDL)
                for stmt in _TELEMETRY_INDEXES:
                    conn.execute(stmt)
                conn.commit()
                self._initialized.add(str(path))
            conn.execute(
                """
                INSERT OR REPLACE INTO telemetry VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    row.schema_version,
                    row.at.isoformat(),
                    row.scope_leaf,
                    row.thread_id,
                    row.run_id,
                    row.actor_kind,
                    row.actor_id,
                    row.worker_id,
                    row.triggered_by_id,
                    row.idempotency_key,
                    row.status,
                    row.stop_reason,
                    row.error_code,
                    row.error_message,
                    row.provider,
                    row.model,
                    row.tokens_input,
                    row.tokens_output,
                    row.tokens_cache_creation,
                    row.tokens_cache_read,
                    row.duration_ms,
                    row.events_emitted,
                    row.tool_calls,
                    row.tool_errors,
                    row.stream_deltas,
                ),
            )
            conn.commit()
        finally:
            conn.close()


class JsonlTelemetrySink(BaseModel):
    path: Path

    model_config = {"arbitrary_types_allowed": True}

    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

    async def write(self, row: TelemetryRow) -> None:
        line = row.model_dump_json() + "\n"
        async with self._lock:
            await asyncio.to_thread(_append_to_file, self.path, line)


class MultiTelemetrySink(BaseModel):
    sinks: list[TelemetrySink]

    model_config = {"arbitrary_types_allowed": True}

    async def write(self, row: TelemetryRow) -> None:
        for sink in self.sinks:
            with contextlib.suppress(Exception):
                await sink.write(row)


class NullTelemetrySink(BaseModel):
    model_config = {"frozen": True}

    async def write(self, row: TelemetryRow) -> None:
        return None


def _append_to_file(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
