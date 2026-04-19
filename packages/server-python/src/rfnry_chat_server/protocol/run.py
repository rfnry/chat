from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rfnry_chat_server.protocol.identity import AssistantIdentity, Identity

RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class RunError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class Run(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    thread_id: str
    assistant: AssistantIdentity
    triggered_by: Identity
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None = None
    error: RunError | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
