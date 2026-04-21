from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from typing import Any, Protocol

from rfnry_chat_protocol import (
    AssistantIdentity,
    Event,
    MessageEvent,
    ReasoningEvent,
    StreamDeltaFrame,
    StreamEndFrame,
    StreamError,
    StreamStartFrame,
    StreamTargetType,
    TextPart,
)


class StreamSink(Protocol):
    async def start(self, frame: StreamStartFrame) -> None: ...
    async def delta(self, frame: StreamDeltaFrame) -> None: ...
    async def end(self, frame: StreamEndFrame) -> None: ...
    async def publish_event(self, event: Event) -> Event: ...


def _new_event_id() -> str:
    return f"evt_{secrets.token_hex(8)}"


class Stream:
    def __init__(
        self,
        sink: StreamSink,
        target_type: StreamTargetType,
        thread_id: str,
        run_id: str,
        author: AssistantIdentity,
        metadata: dict[str, Any] | None,
    ) -> None:
        self._sink = sink
        self._target_type = target_type
        self._thread_id = thread_id
        self._run_id = run_id
        self._author = author
        self._metadata = metadata or {}
        self._buffer: list[str] = []
        self.event_id = ""

    async def __aenter__(self) -> Stream:
        self.event_id = _new_event_id()
        await self._sink.start(
            StreamStartFrame(
                event_id=self.event_id,
                thread_id=self._thread_id,
                run_id=self._run_id,
                target_type=self._target_type,
                author=self._author,
            )
        )
        return self

    async def append(self, text: str) -> None:
        if not text:
            return
        self._buffer.append(text)
        await self._sink.delta(
            StreamDeltaFrame(
                event_id=self.event_id,
                thread_id=self._thread_id,
                text=text,
            )
        )

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            await self._sink.end(
                StreamEndFrame(
                    event_id=self.event_id,
                    thread_id=self._thread_id,
                    error=None,
                )
            )
            await self._sink.publish_event(self._build_event())
            return
        error = self._error_for(exc)
        await self._sink.end(
            StreamEndFrame(
                event_id=self.event_id,
                thread_id=self._thread_id,
                error=error,
            )
        )

    def _build_event(self) -> Event:
        text = "".join(self._buffer)
        now = datetime.now(UTC)
        if self._target_type == "message":
            return MessageEvent(
                id=self.event_id,
                thread_id=self._thread_id,
                run_id=self._run_id,
                author=self._author,
                created_at=now,
                metadata=self._metadata,
                content=[TextPart(text=text)],
            )
        return ReasoningEvent(
            id=self.event_id,
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=now,
            metadata=self._metadata,
            content=text,
        )

    def _error_for(self, exc: Any) -> StreamError:
        if isinstance(exc, asyncio.CancelledError):
            return StreamError(code="cancelled", message="run cancelled")
        if isinstance(exc, TimeoutError):
            return StreamError(code="timeout", message="run timed out")
        return StreamError(code="handler_error", message=str(exc) or type(exc).__name__)
