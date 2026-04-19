from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from rfnry_chat_server.protocol.thread import Thread, ThreadPatch
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def store(clean_db: asyncpg.Pool) -> PostgresChatStore:
    return PostgresChatStore(pool=clean_db)


def _new_thread(id: str = "th_1", tenant: dict[str, str] | None = None) -> Thread:
    now = datetime.now(UTC)
    return Thread(
        id=id,
        tenant=tenant or {},
        metadata={},
        created_at=now,
        updated_at=now,
    )


async def test_create_and_get(store: PostgresChatStore) -> None:
    t = _new_thread(tenant={"org": "A"})
    created = await store.create_thread(t)
    assert created.id == "th_1"

    fetched = await store.get_thread("th_1")
    assert fetched is not None
    assert fetched.tenant == {"org": "A"}


async def test_get_missing_returns_none(store: PostgresChatStore) -> None:
    assert await store.get_thread("nope") is None


async def test_update_thread_tenant(store: PostgresChatStore) -> None:
    await store.create_thread(_new_thread(tenant={"org": "A"}))
    updated = await store.update_thread("th_1", ThreadPatch(tenant={"org": "B"}))
    assert updated.tenant == {"org": "B"}
    assert updated.updated_at >= updated.created_at


async def test_update_thread_metadata_only(store: PostgresChatStore) -> None:
    await store.create_thread(_new_thread(tenant={"org": "A"}))
    updated = await store.update_thread("th_1", ThreadPatch(metadata={"locked": True}))
    assert updated.tenant == {"org": "A"}
    assert updated.metadata == {"locked": True}


async def test_delete_thread(store: PostgresChatStore) -> None:
    await store.create_thread(_new_thread())
    await store.delete_thread("th_1")
    assert await store.get_thread("th_1") is None
