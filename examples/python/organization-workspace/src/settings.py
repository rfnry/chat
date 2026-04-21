from __future__ import annotations

import os
from typing import Literal

Workspace = Literal["legal", "medical"]

_WORKSPACE_CONFIG: dict[Workspace, dict[str, str]] = {
    "legal": {
        "name": "Legal Advisor",
        "system_prompt": (
            "You are a corporate legal advisor. Answer questions about contracts, "
            "case law, and compliance. Use the available tools when you need to "
            "reference prior cases or draft clauses. Keep responses concise and "
            "cite tool output when relevant."
        ),
    },
    "medical": {
        "name": "Medical Reference Assistant",
        "system_prompt": (
            "You are a clinical reference assistant. Answer questions about "
            "symptoms, medications, and drug interactions. Use the available "
            "tools for authoritative data. Always recommend consulting a "
            "qualified clinician for diagnosis or treatment decisions."
        ),
    },
}


def _require_workspace() -> Workspace:
    raw = os.environ.get("WORKSPACE", "legal")
    if raw not in _WORKSPACE_CONFIG:
        allowed = ", ".join(_WORKSPACE_CONFIG)
        raise ValueError(f"WORKSPACE must be one of [{allowed}]; got {raw!r}")
    return raw  # type: ignore[return-value]


class Settings:
    WORKSPACE: Workspace = _require_workspace()
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("PORT", "8001"))
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "postgresql://rfnry_chat:rfnry_chat@localhost:55432/rfnry_chat_test",
    )
    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    ANTHROPIC_MAX_TOKENS: int = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "2048"))

    @property
    def ASSISTANT_ID(self) -> str:
        return f"{self.WORKSPACE}-agent"

    @property
    def ASSISTANT_NAME(self) -> str:
        return _WORKSPACE_CONFIG[self.WORKSPACE]["name"]

    @property
    def ASSISTANT_TOKEN(self) -> str:
        return f"{self.WORKSPACE}-agent-internal-token"

    @property
    def SYSTEM_PROMPT(self) -> str:
        return _WORKSPACE_CONFIG[self.WORKSPACE]["system_prompt"]


settings = Settings()
