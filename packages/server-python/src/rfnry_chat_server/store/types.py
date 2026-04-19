from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ThreadCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    created_at: datetime
    id: str


class EventCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    created_at: datetime
    id: str


class Page(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    items: list[T]
    next_cursor: ThreadCursor | EventCursor | None = None
