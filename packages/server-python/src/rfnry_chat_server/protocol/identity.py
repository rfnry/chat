from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _IdentityBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserIdentity(_IdentityBase):
    role: Literal["user"] = "user"


class AssistantIdentity(_IdentityBase):
    role: Literal["assistant"] = "assistant"


class SystemIdentity(_IdentityBase):
    role: Literal["system"] = "system"


Identity = UserIdentity | AssistantIdentity | SystemIdentity

_identity_adapter: TypeAdapter[Identity] = TypeAdapter(
    UserIdentity | AssistantIdentity | SystemIdentity,
)


def parse_identity(raw: dict[str, Any]) -> Identity:
    return _identity_adapter.validate_python(raw)
