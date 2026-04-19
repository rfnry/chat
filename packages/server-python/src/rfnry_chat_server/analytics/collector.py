from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    properties: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = None
    run_id: str | None = None
    assistant_id: str | None = None
    timestamp: datetime


OnAnalyticsCallback = Callable[[list[AnalyticsEvent]], Awaitable[None]]


class AssistantAnalytics:
    def __init__(
        self,
        on_analytics: OnAnalyticsCallback | None,
        thread_id: str,
        run_id: str,
        assistant_id: str,
    ) -> None:
        self._on_analytics = on_analytics
        self._thread_id = thread_id
        self._run_id = run_id
        self._assistant_id = assistant_id
        self._buffer: list[AnalyticsEvent] = []

    def track(self, name: str, properties: dict[str, Any] | None = None) -> None:
        self._buffer.append(
            AnalyticsEvent(
                name=name,
                properties=properties or {},
                thread_id=self._thread_id,
                run_id=self._run_id,
                assistant_id=self._assistant_id,
                timestamp=datetime.now(UTC),
            )
        )

    async def flush(self) -> None:
        if not self._buffer or self._on_analytics is None:
            self._buffer = []
            return
        events = self._buffer
        self._buffer = []
        await self._on_analytics(events)
