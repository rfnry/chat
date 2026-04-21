from __future__ import annotations

import logging
from typing import Any

from rfnry_chat_client import ChatClient
from rfnry_chat_protocol import AssistantIdentity

from src.agent import assistant
from src.settings import settings

logger = logging.getLogger("cs.agent.client")


def create_chat_client(base_url: str) -> ChatClient:
    identity = AssistantIdentity(id=settings.ASSISTANT_ID, name=settings.ASSISTANT_NAME)

    async def authenticate() -> dict[str, Any]:
        return {"auth": {"token": settings.ASSISTANT_TOKEN}}

    chat_client = ChatClient(base_url=base_url, identity=identity, authenticate=authenticate)
    assistant.register(chat_client, identity)
    logger.info("agent client built id=%s base_url=%s", identity.id, base_url)
    return chat_client
