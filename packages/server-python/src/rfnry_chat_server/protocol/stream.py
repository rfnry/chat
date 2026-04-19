from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from rfnry_chat_server.protocol.identity import AssistantIdentity

StreamTargetType = Literal["message", "reasoning"]


class StreamError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class StreamStartFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    thread_id: str
    run_id: str
    target_type: StreamTargetType
    author: AssistantIdentity


class StreamDeltaFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    thread_id: str
    text: str


class StreamEndFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    thread_id: str
    error: StreamError | None = None
