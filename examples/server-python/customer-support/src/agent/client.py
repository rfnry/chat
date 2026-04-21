from __future__ import annotations

import asyncio
import logging
from typing import Any

from rfnry_chat_client import ChatClient
from rfnry_chat_protocol import AssistantIdentity

from src.agent import assistant
from src.settings import settings

logger = logging.getLogger("cs.agent.client")

_CONNECT_RETRIES = 50
_CONNECT_BACKOFF_SECONDS = 0.2


def build(base_url: str) -> ChatClient:
    identity = AssistantIdentity(id=settings.ASSISTANT_ID, name=settings.ASSISTANT_NAME)

    async def authenticate() -> dict[str, Any]:
        return {"auth": {"token": settings.ASSISTANT_TOKEN}}

    chat_client = ChatClient(base_url=base_url, identity=identity, authenticate=authenticate)
    assistant.register(chat_client, identity)
    logger.info("agent client built id=%s base_url=%s", identity.id, base_url)
    return chat_client


async def run(chat_client: ChatClient) -> None:
    for attempt in range(1, _CONNECT_RETRIES + 1):
        try:
            await chat_client.connect()
            logger.info("agent connected on attempt=%d", attempt)
            break
        except Exception as exc:
            logger.debug("agent connect retry=%d: %s", attempt, exc)
            await asyncio.sleep(_CONNECT_BACKOFF_SECONDS)
    else:
        logger.error("agent failed to connect after %d attempts", _CONNECT_RETRIES)
        return

    try:
        await asyncio.Event().wait()
    finally:
        await chat_client.disconnect()
        logger.info("agent disconnected")
