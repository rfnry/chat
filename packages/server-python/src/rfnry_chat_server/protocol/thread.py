from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rfnry_chat_server.protocol.identity import Identity
from rfnry_chat_server.protocol.tenant import TenantScope


class Thread(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    tenant: TenantScope = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ThreadPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant: TenantScope | None = None
    metadata: dict[str, Any] | None = None


class ThreadMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str
    identity_id: str
    identity: Identity
    role: str = "member"
    added_at: datetime
    added_by: Identity
