from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, PrivateAttr

from rfnry_chat_client.telemetry.record import TelemetryRow

try:
    import asyncpg  # type: ignore[import-not-found,import-untyped]  # noqa: F401 — import-time guard
except ImportError as exc:  # pragma: no cover — import-time guard
    raise ImportError(
        "rfnry_chat_client.telemetry.postgres requires the `asyncpg` driver. "
        "Install with `pip install 'rfnry-chat-client[postgres]'` or `uv sync --extra postgres`."
    ) from exc


_TELEMETRY_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    schema_version INTEGER NOT NULL,
    at TIMESTAMPTZ NOT NULL,
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
    "CREATE INDEX IF NOT EXISTS idx_{table}_scope_at ON {table}(scope_leaf, at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_{table}_worker_at ON {table}(scope_leaf, worker_id, at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_{table}_status ON {table}(scope_leaf, status, at DESC)",
)

_INSERT_SQL = """
INSERT INTO {table} (
    schema_version, at, scope_leaf, thread_id, run_id, actor_kind, actor_id, worker_id,
    triggered_by_id, idempotency_key, status, stop_reason, error_code, error_message,
    provider, model,
    tokens_input, tokens_output, tokens_cache_creation, tokens_cache_read,
    duration_ms, events_emitted, tool_calls, tool_errors, stream_deltas
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
    $21, $22, $23, $24, $25
)
ON CONFLICT (scope_leaf, thread_id, run_id) DO NOTHING
"""


class PostgresTelemetrySink(BaseModel):
    pool: Any
    table: str = "rfnry_chat_telemetry"

    model_config = {"arbitrary_types_allowed": True}

    _initialized: bool = PrivateAttr(default=False)
    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

    async def write(self, row: TelemetryRow) -> None:
        async with self._lock:
            if not self._initialized:
                await self._ensure_schema()
                self._initialized = True
            await self._insert(row)

    async def _ensure_schema(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(_TELEMETRY_DDL.format(table=self.table))
            for stmt in _TELEMETRY_INDEXES:
                await conn.execute(stmt.format(table=self.table))

    async def _insert(self, row: TelemetryRow) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                _INSERT_SQL.format(table=self.table),
                row.schema_version,
                row.at,
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
            )
