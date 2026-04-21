from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    AGENT_ID: str = os.environ.get("AGENT_ID", "a_monitor")
    AGENT_NAME: str = os.environ.get("AGENT_NAME", "Monitor")
    AGENT_TOKEN: str = os.environ.get("AGENT_TOKEN", "monitor-secret")
    DEFAULT_CHAT_SERVER_URL: str = os.environ.get("DEFAULT_CHAT_SERVER_URL", "http://localhost:8000")
    PORT: int = int(os.environ.get("PORT", "9100"))


settings = Settings()
