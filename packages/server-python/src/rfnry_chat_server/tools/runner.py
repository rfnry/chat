from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from rfnry_chat_protocol import (
    Run,
    RunError,
    SystemIdentity,
    Thread,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
)

from rfnry_chat_server.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from rfnry_chat_server.server.chat_server import ChatServer


@dataclass(frozen=True)
class ToolCallContext:
    event: ToolCallEvent
    thread: Thread
    run: Run


class ToolRunner:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        server: ChatServer,
        timeout_seconds: int,
        system_identity: SystemIdentity,
    ) -> None:
        self._registry = registry
        self._server = server
        self._timeout = timeout_seconds
        self._system = system_identity

    async def handle(self, event: ToolCallEvent, thread: Thread) -> None:
        handler = self._registry.get(event.tool.name)
        if handler is None:
            return
        run = await self._server.begin_run(
            thread=thread,
            actor=self._system,
            triggered_by=event.author,
            idempotency_key=None,
        )
        ctx = ToolCallContext(event=event, thread=thread, run=run)
        try:
            result = await asyncio.wait_for(handler(ctx), timeout=self._timeout)
        except asyncio.CancelledError:
            await self._server.end_run(
                run_id=run.id,
                error=RunError(code="cancelled", message="handler cancelled"),
            )
            raise
        except TimeoutError:
            err = RunError(code="timeout", message=f"tool exceeded {self._timeout}s")
            await self._server.publish_event(
                self._tool_result_event(event=event, thread=thread, run=run, result=None, error=err),
                thread=thread,
            )
            await self._server.end_run(run_id=run.id, error=err)
            return
        except Exception as exc:
            err = RunError(code="handler_error", message=str(exc))
            await self._server.publish_event(
                self._tool_result_event(event=event, thread=thread, run=run, result=None, error=err),
                thread=thread,
            )
            await self._server.end_run(run_id=run.id, error=err)
            return

        await self._server.publish_event(
            self._tool_result_event(event=event, thread=thread, run=run, result=result, error=None),
            thread=thread,
        )
        await self._server.end_run(run_id=run.id, error=None)

    def _tool_result_event(
        self,
        *,
        event: ToolCallEvent,
        thread: Thread,
        run: Run,
        result: Any,
        error: RunError | None,
    ) -> ToolResultEvent:
        error_payload: dict[str, Any] | None = None
        if error is not None:
            error_payload = {"code": error.code, "message": error.message}
        return ToolResultEvent(
            id=f"evt_{secrets.token_hex(8)}",
            thread_id=thread.id,
            run_id=run.id,
            author=self._system,
            created_at=datetime.now(UTC),
            recipients=[event.author.id],
            tool=ToolResult(id=event.tool.id, result=result, error=error_payload),
        )
