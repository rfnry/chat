from __future__ import annotations

import logging
from typing import Any

from rfnry_chat_client import ChatClient, ChatClientPool
from rfnry_chat_protocol import AssistantIdentity, TextPart, ThreadInvitedFrame

from src.settings import settings

logger = logging.getLogger("monitoring-assistant")


def _identity() -> AssistantIdentity:
    return AssistantIdentity(id=settings.AGENT_ID, name=settings.AGENT_NAME)


def build_client(base_url: str) -> ChatClient:
    identity = _identity()

    async def authenticate() -> dict[str, Any]:
        return {"auth": {"token": settings.AGENT_TOKEN}}

    client = ChatClient(base_url=base_url, identity=identity, authenticate=authenticate)

    @client.on_invited()
    async def on_invited(frame: ThreadInvitedFrame) -> None:
        logger.info(
            "invited thread=%s by=%s — auto-joined",
            frame.thread.id,
            frame.added_by.id,
        )

    @client.on_message()
    async def reply(ctx, send):
        # Minimal acknowledgement — real agents plug in an LLM here.
        yield send.message(content=[TextPart(text="Monitor acknowledged.")])

    return client


def build_pool() -> ChatClientPool:
    return ChatClientPool(factory=build_client)
