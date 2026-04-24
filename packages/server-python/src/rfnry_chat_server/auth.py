from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from rfnry_chat_protocol import Identity


class HandshakeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    headers: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, Any] = Field(default_factory=dict)


class AuthenticateCallback(Protocol):
    async def __call__(self, handshake: HandshakeData) -> Identity | None: ...


class AuthorizeCallback(Protocol):
    async def __call__(
        self,
        identity: Identity,
        thread_id: str,
        action: str,
        *,
        target_id: str | None = None,
    ) -> bool: ...
