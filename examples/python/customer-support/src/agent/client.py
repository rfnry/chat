from __future__ import annotations

from rfnry_chat_client import ChatClient
from rfnry_chat_protocol import AssistantIdentity

from src.agent import assistant

ASSISTANT_ID = "cs-agent"
ASSISTANT_NAME = "Customer Support"


def create_chat_client(base_url: str) -> ChatClient:
    identity = AssistantIdentity(id=ASSISTANT_ID, name=ASSISTANT_NAME)
    chat_client = ChatClient(base_url=base_url, identity=identity)
    assistant.register(chat_client, identity)
    print("agent client built id=%s base_url=%s", identity.id, base_url)
    return chat_client
