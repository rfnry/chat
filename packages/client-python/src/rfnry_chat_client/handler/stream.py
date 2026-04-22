from __future__ import annotations

import secrets
from datetime import UTC, datetime
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal

from rfnry_chat_protocol import (
    Identity,
    MessageEvent,
    ReasoningEvent,
    StreamDeltaFrame,
    StreamEndFrame,
    StreamError,
    StreamTargetType,
    TextPart,
)

if TYPE_CHECKING:
    from rfnry_chat_client.client import ChatClient


class Stream:
    def __init__(
        self,
        *,
        client: ChatClient,
        thread_id: str,
        run_id: str,
        author: Identity,
        target_type: StreamTargetType,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._thread_id = thread_id
        self._run_id = run_id
        self._author = author
        self._target_type = target_type
        self._metadata = metadata or {}
        self._event_id = f"evt_{secrets.token_hex(8)}"
        self._buffer: list[str] = []
        self._started = False
        self._finalized: MessageEvent | ReasoningEvent | None = None

    @property
    def event_id(self) -> str:
        return self._event_id

    @property
    def finalized_event(self) -> MessageEvent | ReasoningEvent | None:
        return self._finalized

    async def __aenter__(self) -> Stream:
        # Build the wire payload directly. `StreamStartFrame.author` is typed
        # as `AssistantIdentity` in the shared protocol schema, but
        # client-side we do not runtime-gate on role — the server is the
        # authority on who may stream. Every identity variant serializes to
        # the same shape, so skipping the pydantic model here preserves the
        # wire contract without reintroducing a role gate.
        payload: dict[str, Any] = {
            "event_id": self._event_id,
            "thread_id": self._thread_id,
            "run_id": self._run_id,
            "target_type": self._target_type,
            "author": self._author.model_dump(mode="json"),
        }
        await self._client.socket.send_stream_start(payload)
        self._started = True
        return self

    async def write(self, text: str) -> None:
        if not self._started:
            raise RuntimeError("stream.write called before __aenter__")
        if not text:
            return
        self._buffer.append(text)
        frame = StreamDeltaFrame(
            event_id=self._event_id,
            thread_id=self._thread_id,
            text=text,
        )
        await self._client.socket.send_stream_delta(
            frame.model_dump(mode="json", by_alias=True)
        )

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        error: StreamError | None = None
        if exc is not None:
            error = StreamError(code="handler_error", message=str(exc))
        end_frame = StreamEndFrame(
            event_id=self._event_id,
            thread_id=self._thread_id,
            error=error,
        )
        await self._client.socket.send_stream_end(
            end_frame.model_dump(mode="json", by_alias=True)
        )

        if exc is None:
            content = "".join(self._buffer)
            final: MessageEvent | ReasoningEvent
            if self._target_type == "message":
                final = MessageEvent(
                    id=self._event_id,
                    thread_id=self._thread_id,
                    run_id=self._run_id,
                    author=self._author,
                    created_at=datetime.now(UTC),
                    metadata=self._metadata,
                    content=[TextPart(text=content)],
                )
            else:
                final = ReasoningEvent(
                    id=self._event_id,
                    thread_id=self._thread_id,
                    run_id=self._run_id,
                    author=self._author,
                    created_at=datetime.now(UTC),
                    metadata=self._metadata,
                    content=content,
                )
            await self._client.emit_event(final)
            self._finalized = final
        return False
