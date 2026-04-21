from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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

from rfnry_chat_client.handler.stream import Stream

if TYPE_CHECKING:
    from rfnry_chat_client.client import ChatClient


class HandlerSend:
    def __init__(
        self,
        *,
        thread_id: str,
        author: Identity,
        run_id: str | None = None,
        client: ChatClient | None = None,
    ) -> None:
        self._thread_id = thread_id
        self._author = author
        self._run_id = run_id
        self._client = client

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


    def message_stream(self, *, metadata: dict[str, Any] | None = None) -> Stream:
        return self._make_stream("message", metadata=metadata)

    def reasoning_stream(self, *, metadata: dict[str, Any] | None = None) -> Stream:
        return self._make_stream("reasoning", metadata=metadata)

    def _make_stream(
        self,
        target_type: str,
        *,
        metadata: dict[str, Any] | None,
    ) -> Stream:
        if self._client is None:
            raise RuntimeError(
                "streaming requires a ChatClient; HandlerSend was constructed without one"
            )
        if self._run_id is None:
            raise RuntimeError(
                "streaming requires a run_id; register the handler with in_run=True"
            )
        return Stream(
            client=self._client,
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            target_type=target_type,  # type: ignore[arg-type]
            metadata=metadata,
        )


def _new_id() -> str:
    return f"evt_{secrets.token_hex(8)}"
