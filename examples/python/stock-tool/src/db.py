from __future__ import annotations

from typing import Any

import asyncpg
from rfnry_chat_server import PostgresChatStore


async def create_pool(database_url: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=10, command_timeout=30)
    assert pool is not None
    return pool


class LazyStore:
    def __init__(self) -> None:
        self._real: PostgresChatStore | None = None

    def bind(self, pool: asyncpg.Pool) -> None:
        self._real = PostgresChatStore(pool=pool)

    def __getattr__(self, name: str) -> Any:
        real = self.__dict__.get("_real")
        if real is None:
            raise RuntimeError(f"LazyStore not bound; cannot access {name!r}")
        return getattr(real, name)
