from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rfnry_chat_protocol import Event, Thread

from rfnry_chat_server.store.protocol import ChatStore

if TYPE_CHECKING:
    from rfnry_chat_server.server.chat_server import ChatServer


@dataclass(frozen=True)
class HandlerContext:
    event: Event
    thread: Thread
    store: ChatStore
    server: ChatServer
