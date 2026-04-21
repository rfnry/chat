from __future__ import annotations

import logging

from rfnry_chat_client import ChatClient
from rfnry_chat_protocol import AssistantIdentity

from src.agent_medical import assistant

ASSISTANT_ID = "medical-agent"
ASSISTANT_NAME = "Medical Reference Assistant"

logger = logging.getLogger("org.medical.agent.client")


def create_chat_client(base_url: str) -> ChatClient:
    identity = AssistantIdentity(
        id=ASSISTANT_ID,
        name=ASSISTANT_NAME,
        metadata={"tenant": {"workspace": "medical"}},
    )
    client = ChatClient(base_url=base_url, identity=identity)
    assistant.register(client, identity)
    logger.info("medical agent built id=%s base_url=%s", identity.id, base_url)
    return client
