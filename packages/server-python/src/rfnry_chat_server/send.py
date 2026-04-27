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

if TYPE_CHECKING:
    from rfnry_chat_server.server import ChatServer


class Send:
    def __init__(
        self,
        *,
        thread_id: str,
        author: Identity,
        run_id: str | None = None,
        run_starter: Callable[[], Awaitable[str]] | None = None,
        server: ChatServer | None = None,
    ) -> None:
        self._thread_id = thread_id
        self._author = author
        self._run_id = run_id
        self._run_starter = run_starter
        self._server = server

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
        if self._server is None:
            raise RuntimeError("Send.emit requires a ChatServer; Send was constructed without one")
        updates: dict[str, Any] = {"created_at": datetime.now(UTC)}
        if event.run_id is None:
            if self._run_id is not None:
                updates["run_id"] = self._run_id
            elif self._run_starter is not None:
                updates["run_id"] = await self.ensure_run_id()
        fresh = event.model_copy(update=updates)
        return await self._server.publish_event(fresh)

    def message(
        self,
        content: list[ContentPart],
        *,
        recipients: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MessageEvent:
        return MessageEvent(
            id=_new_id(),
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
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
