from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))


class FakeSioClient:
    def __init__(self) -> None:
        self.connected_url: str | None = None
        self.connected_auth: dict[str, Any] | None = None
        self.headers_sent: dict[str, str] | None = None
        self.handlers: dict[str, Any] = {}
        self.emitted: list[tuple[str, Any]] = []
        self.ack_replies: dict[str, Any] = {}
        self.disconnected = False

    async def connect(
        self,
        url: str,
        *,
        auth: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        transports: list[str] | None = None,
        socketio_path: str | None = None,
    ) -> None:
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

    async def call(self, event: str, data: Any = None, *, timeout: float | None = None) -> Any:
        self.emitted.append((event, data))
        return self.ack_replies.get(event, {})
