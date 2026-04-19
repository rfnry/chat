from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from rfnry_chat_server.protocol.content import ContentPart
from rfnry_chat_server.protocol.identity import Identity
from rfnry_chat_server.protocol.tenant import TenantScope


class _EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str
    thread_id: str
    run_id: str | None = None
    author: Identity
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    client_id: str | None = None
    recipients: list[str] | None = None


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    arguments: Any


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    result: Any | None = None
    error: dict[str, Any] | None = None


class _EventError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class _ThreadCreatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    tenant: TenantScope


class MessageEvent(_EventBase):
    type: Literal["message"] = "message"
    content: list[ContentPart]


class ReasoningEvent(_EventBase):
    type: Literal["reasoning"] = "reasoning"
    content: str


class ToolCallEvent(_EventBase):
    type: Literal["tool.call"] = "tool.call"
    tool: ToolCall


class ToolResultEvent(_EventBase):
    type: Literal["tool.result"] = "tool.result"
    tool: ToolResult


class ThreadCreatedEvent(_EventBase):
    type: Literal["thread.created"] = "thread.created"
    thread: _ThreadCreatedPayload


class ThreadMemberAddedEvent(_EventBase):
    type: Literal["thread.member_added"] = "thread.member_added"
    member: Identity


class ThreadMemberRemovedEvent(_EventBase):
    type: Literal["thread.member_removed"] = "thread.member_removed"
    member: Identity


class ThreadTenantChangedEvent(_EventBase):
    type: Literal["thread.tenant_changed"] = "thread.tenant_changed"
    from_: TenantScope = Field(alias="from", serialization_alias="from")
    to: TenantScope


class RunStartedEvent(_EventBase):
    type: Literal["run.started"] = "run.started"


class RunCompletedEvent(_EventBase):
    type: Literal["run.completed"] = "run.completed"


class RunFailedEvent(_EventBase):
    type: Literal["run.failed"] = "run.failed"
    error: _EventError


class RunCancelledEvent(_EventBase):
    type: Literal["run.cancelled"] = "run.cancelled"


Event = (
    MessageEvent
    | ReasoningEvent
    | ToolCallEvent
    | ToolResultEvent
    | ThreadCreatedEvent
    | ThreadMemberAddedEvent
    | ThreadMemberRemovedEvent
    | ThreadTenantChangedEvent
    | RunStartedEvent
    | RunCompletedEvent
    | RunFailedEvent
    | RunCancelledEvent
)

_event_adapter: TypeAdapter[Event] = TypeAdapter(
    Annotated[Event, Field(discriminator="type")],
)


def parse_event(raw: dict[str, Any]) -> Event:
    return _event_adapter.validate_python(raw)


class EventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str
    content: list[ContentPart] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    recipients: list[str] | None = None
