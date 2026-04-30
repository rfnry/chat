from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))


class FakeSioClient:
    def __init__(self, *, connect_raises: Exception | None = None) -> None:
        self.connected_url: str | None = None
        self.connected_auth: dict[str, Any] | None = None
        self.headers_sent: dict[str, str] | None = None
        self.handlers: dict[str, Any] = {}

        self.emitted: list[tuple[str, Any]] = []
        self.emit_calls: list[tuple[str, Any]] = []
        self.call_calls: list[tuple[str, Any]] = []
        self.calls: list[tuple[str, Any]] = []
        self.ack_replies: dict[str, Any] = {}
        self.disconnected = False
        self._connect_raises = connect_raises

    async def connect(
        self,
        url: str,
        *,
        auth: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        transports: list[str] | None = None,
        socketio_path: str | None = None,
    ) -> None:
        if self._connect_raises is not None:
            raise self._connect_raises
        self.connected_url = url
        self.connected_auth = auth
        self.headers_sent = headers

    async def disconnect(self) -> None:
        self.disconnected = True

    def on(self, event: str, handler: Any = None) -> Any:
        if handler is None:

            def decorator(fn: Any) -> Any:
                self.handlers[event] = fn
                return fn

            return decorator
        self.handlers[event] = handler

    async def emit(self, event: str, data: Any = None) -> None:

        self.emitted.append((event, data))
        self.emit_calls.append((event, data))

    async def call(self, event: str, data: Any = None, *, timeout: float | None = None) -> Any:

        self.emitted.append((event, data))
        self.call_calls.append((event, data))
        self.calls.append((event, data))
        if event in self.ack_replies:
            return self.ack_replies[event]
        if event == "message:send":
            draft = data["draft"] if isinstance(data, dict) else {}
            now = datetime.now(UTC).isoformat()
            return {
                "event": {
                    "id": "evt_stub",
                    "thread_id": data["thread_id"] if isinstance(data, dict) else "t_stub",
                    "author": {
                        "role": "assistant",
                        "id": "a_me",
                        "name": "Me",
                        "metadata": {},
                    },
                    "created_at": now,
                    "metadata": draft.get("metadata") or {},
                    "client_id": draft.get("client_id"),
                    "recipients": draft.get("recipients"),
                    "type": "message",
                    "content": draft.get("content") or [],
                }
            }
        return {}
