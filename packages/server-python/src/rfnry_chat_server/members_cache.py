from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from rfnry_chat_protocol import ThreadMember

from rfnry_chat_server.observability import Observability

if TYPE_CHECKING:
    from rfnry_chat_server.store.protocol import ChatStore


class MembersCache:
    def __init__(
        self,
        store: ChatStore,
        *,
        ttl_seconds: float = 5.0,
        observability: Observability | None = None,
    ) -> None:
        self._store = store
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, list[ThreadMember]]] = {}
        self._inflight: dict[str, asyncio.Future[list[ThreadMember]]] = {}
        self._observability = observability

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    async def get(self, thread_id: str) -> list[ThreadMember]:
        if not self.enabled:
            return await self._store.list_members(thread_id)
        entry = self._entries.get(thread_id)
        if entry is not None and time.monotonic() - entry[0] < self._ttl:
            return list(entry[1])
        inflight = self._inflight.get(thread_id)
        if inflight is not None:
            return list(await inflight)
        return list(await self._fetch(thread_id))

    async def _fetch(self, thread_id: str) -> list[ThreadMember]:
        future: asyncio.Future[list[ThreadMember]] = asyncio.get_running_loop().create_future()
        self._inflight[thread_id] = future
        try:
            members = await self._store.list_members(thread_id)
        except BaseException as exc:
            if self._observability is not None:
                await self._observability.log(
                    "members_cache.fetch_failed",
                    level="error",
                    thread_id=thread_id,
                    error=exc,
                )
            if not future.done():
                future.set_exception(exc)
            self._inflight.pop(thread_id, None)
            raise
        self._entries[thread_id] = (time.monotonic(), members)
        future.set_result(members)
        self._inflight.pop(thread_id, None)
        return members

    def invalidate(self, thread_id: str) -> None:
        self._entries.pop(thread_id, None)

    def clear(self) -> None:
        self._entries.clear()
        self._inflight.clear()
