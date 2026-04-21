from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rfnry_chat_protocol import Event, Identity

if TYPE_CHECKING:
    from rfnry_chat_client.client import ChatClient


@dataclass(frozen=True)
class HandlerContext:
    event: Event
    identity: Identity
    client: ChatClient
