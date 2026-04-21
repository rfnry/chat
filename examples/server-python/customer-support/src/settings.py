from __future__ import annotations

import os


class Settings:
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("PORT", "8000"))
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "postgresql://rfnry_chat:rfnry_chat@localhost:55432/rfnry_chat_test",
    )
    ASSISTANT_ID: str = os.environ.get("ASSISTANT_ID", "cs-agent")
    ASSISTANT_NAME: str = os.environ.get("ASSISTANT_NAME", "Customer Support")
    ASSISTANT_TOKEN: str = os.environ.get("ASSISTANT_TOKEN", "cs-agent-internal-token")
    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    ANTHROPIC_MAX_TOKENS: int = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "2048"))


settings = Settings()
