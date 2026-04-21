from __future__ import annotations

from typing import Literal


class ChatHttpError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class ThreadNotFoundError(ChatHttpError):
    def __init__(self, body: str) -> None:
        super().__init__(404, body)


class ChatAuthError(ChatHttpError):
    def __init__(self, status: Literal[401, 403], body: str) -> None:
        if status not in (401, 403):
            raise ValueError(f"ChatAuthError requires status 401 or 403, got {status}")
        super().__init__(status, body)


class ThreadConflictError(ChatHttpError):
    def __init__(self, body: str) -> None:
        super().__init__(409, body)


def http_error_for(status: int, body: str) -> ChatHttpError:
    if status == 404:
        return ThreadNotFoundError(body)
    if status in (401, 403):
        return ChatAuthError(status, body)  # type: ignore[arg-type]
    if status == 409:
        return ThreadConflictError(body)
    return ChatHttpError(status, body)
