from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ActorKind = Literal["user", "assistant", "system"]
RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class TelemetryRow(BaseModel):
    schema_version: int = 1
    at: datetime

    scope_leaf: str
    thread_id: str
    run_id: str
    actor_kind: ActorKind
    actor_id: str
    worker_id: str
    triggered_by_id: str
    idempotency_key: str | None = None

    status: RunStatus
    stop_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    provider: str | None = None
    model: str | None = None

    tokens_input: int = 0
    tokens_output: int = 0
    tokens_cache_creation: int = 0
    tokens_cache_read: int = 0

    duration_ms: int = 0

    events_emitted: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    stream_deltas: int = 0

    model_config = {"frozen": True}
