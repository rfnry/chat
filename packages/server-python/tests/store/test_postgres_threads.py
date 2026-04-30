from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest
from rfnry_chat_protocol import Thread, ThreadPatch

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


async def test_find_thread_by_client_id_returns_match(store: PostgresChatStore) -> None:
    await store.create_thread(_new_thread(id="th_1"), caller_identity_id="u_alice", client_id="ck-1")
    found = await store.find_thread_by_client_id("u_alice", "ck-1")
    assert found is not None
    assert found.id == "th_1"


async def test_find_thread_by_client_id_scoped_per_caller(store: PostgresChatStore) -> None:
    await store.create_thread(_new_thread(id="th_1"), caller_identity_id="u_alice", client_id="ck-shared")
    await store.create_thread(_new_thread(id="th_2"), caller_identity_id="u_bob", client_id="ck-shared")
    alice_found = await store.find_thread_by_client_id("u_alice", "ck-shared")
    bob_found = await store.find_thread_by_client_id("u_bob", "ck-shared")
    assert alice_found is not None and alice_found.id == "th_1"
    assert bob_found is not None and bob_found.id == "th_2"


async def test_find_thread_by_client_id_returns_none_when_absent(
    store: PostgresChatStore,
) -> None:
    await store.create_thread(_new_thread(id="th_1"))
    assert await store.find_thread_by_client_id("u_alice", "ck-nope") is None


async def test_create_thread_without_client_id_is_not_indexed(
    store: PostgresChatStore,
) -> None:

    await store.create_thread(_new_thread(id="th_1"), caller_identity_id="u_alice")
    assert await store.find_thread_by_client_id("u_alice", "anything") is None
