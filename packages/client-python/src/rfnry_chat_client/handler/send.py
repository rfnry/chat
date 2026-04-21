from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from rfnry_chat_protocol import (
    ContentPart,
    Identity,
    MessageEvent,
    ReasoningEvent,
    ToolCall,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
)


class HandlerSend:
    def __init__(
        self,
        *,
        thread_id: str,
        author: Identity,
        run_id: str | None = None,
    ) -> None:
        self._thread_id = thread_id
        self._author = author
        self._run_id = run_id

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


def _new_id() -> str:
    return f"evt_{secrets.token_hex(8)}"
