from __future__ import annotations

import asyncio
from collections.abc import Callable

from rfnry_chat_client.client import ChatClient

ClientFactory = Callable[[str], ChatClient]


class ChatClientPool:
    def __init__(self, *, factory: ClientFactory) -> None:
        self._factory = factory
        self._clients: dict[str, ChatClient] = {}
        self._lock = asyncio.Lock()

    async def get_or_connect(self, base_url: str) -> ChatClient:

        async with self._lock:
            existing = self._clients.get(base_url)
            if existing is not None:
                return existing
            client = self._factory(base_url)
            await client.connect()
            self._clients[base_url] = client
            return client

    async def close(self, base_url: str) -> None:

        async with self._lock:
            client = self._clients.pop(base_url, None)
        if client is not None:
            await client.disconnect()

    async def close_all(self) -> None:

        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            await client.disconnect()


__all__ = ["ChatClientPool", "ClientFactory"]
