from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from rfnry_chat_protocol import (
    ContentPart,
    Event,
    Identity,
    MessageEvent,
    ReasoningEvent,
    ToolCall,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
)

from rfnry_chat_client.stream import Stream

if TYPE_CHECKING:
    from rfnry_chat_client.client import ChatClient


class Send:
    def __init__(
        self,
        *,
        thread_id: str,
        author: Identity,
        run_id: str | None = None,
        client: ChatClient | None = None,
        run_starter: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._thread_id = thread_id
        self._author = author
        self._run_id = run_id
        self._client = client
        self._run_starter = run_starter

    @property
    def run_id(self) -> str | None:
        return self._run_id

    def set_run_id(self, run_id: str) -> None:
        self._run_id = run_id

    async def ensure_run_id(self) -> str:
        if self._run_id is not None:
            return self._run_id
        if self._run_starter is None:
            raise RuntimeError("Send has no run_id and no run_starter; cannot lazily start a run")
        run_id = await self._run_starter()
        self._run_id = run_id
        return run_id

    async def emit(self, event: Event) -> Event:
        if self._client is None:
            raise RuntimeError("Send.emit requires a ChatClient; Send was constructed without one")
        return await self._client.emit_event(event)

    def message(
        self,
        content: list[ContentPart],
        *,
        recipients: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        client_id: str | None = None,
    ) -> MessageEvent:
        return MessageEvent(
            id=_new_id(),
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
            client_id=client_id,
            recipients=recipients,
            content=content,
        )

    def reasoning(
        self,
        text: str,
        *,
        recipients: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReasoningEvent:
        return ReasoningEvent(
            id=_new_id(),
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
            recipients=recipients,
            content=text,
        )

    def tool_call(
        self,
        name: str,
        arguments: Any,
        *,
        id: str | None = None,
        recipients: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolCallEvent:
        return ToolCallEvent(
            id=_new_id(),
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
            recipients=recipients,
            tool=ToolCall(
                id=id or f"call_{secrets.token_hex(8)}",
                name=name,
                arguments=arguments,
            ),
        )

    def tool_result(
        self,
        tool_id: str,
        result: Any | None = None,
        error: dict[str, Any] | None = None,
        *,
        recipients: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResultEvent:
        return ToolResultEvent(
            id=_new_id(),
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
            recipients=recipients,
            tool=ToolResult(id=tool_id, result=result, error=error),
        )

    def message_stream(
        self,
        *,
        recipients: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> Stream:
        return self._make_stream("message", recipients=recipients, metadata=metadata, run_id=run_id)

    def reasoning_stream(
        self,
        *,
        recipients: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> Stream:
        return self._make_stream("reasoning", recipients=recipients, metadata=metadata, run_id=run_id)

    def _make_stream(
        self,
        target_type: str,
        *,
        recipients: list[str] | None,
        metadata: dict[str, Any] | None,
        run_id: str | None,
    ) -> Stream:
        if self._client is None:
            raise RuntimeError("streaming requires a ChatClient; Send was constructed without one")
        effective_run_id = run_id or self._run_id
        if effective_run_id is None and self._run_starter is None:
            raise RuntimeError(
                "streaming requires a run_id. Either write the handler as an async generator "
                "(auto-wrapped in a Run), or open a run manually via client.begin_run(...) "
                "and pass it as send.message_stream(run_id=run.id)."
            )
        return Stream(
            client=self._client,
            thread_id=self._thread_id,
            run_id=effective_run_id,
            author=self._author,
            target_type=target_type,  # type: ignore[arg-type]
            metadata=metadata,
            recipients=recipients,
            run_resolver=(self.ensure_run_id if effective_run_id is None else None),
        )


def _new_id() -> str:
    return f"evt_{secrets.token_hex(8)}"
