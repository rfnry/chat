from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from rfnry_chat_server.protocol.identity import AssistantIdentity, UserIdentity
from rfnry_chat_server.protocol.thread import Thread
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def store(clean_db: asyncpg.Pool) -> PostgresChatStore:
    s = PostgresChatStore(pool=clean_db)
    now = datetime.now(UTC)
    await s.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    return s


async def test_add_and_list_members(store: PostgresChatStore) -> None:
    user = UserIdentity(id="u1", name="Alice")
    asst = AssistantIdentity(id="a1", name="Helper")
    sys = UserIdentity(id="u_sys", name="System")

    await store.add_member("th_1", user, added_by=sys)
    await store.add_member("th_1", asst, added_by=sys)

    members = await store.list_members("th_1")
    assert len(members) == 2
    ids = {m.identity_id for m in members}
    assert ids == {"u1", "a1"}


async def test_is_member(store: PostgresChatStore) -> None:
    user = UserIdentity(id="u1", name="Alice")
    await store.add_member("th_1", user, added_by=user)
    assert await store.is_member("th_1", "u1") is True
    assert await store.is_member("th_1", "u2") is False


async def test_remove_member(store: PostgresChatStore) -> None:
    user = UserIdentity(id="u1", name="Alice")
    await store.add_member("th_1", user, added_by=user)
    await store.remove_member("th_1", "u1")
    assert await store.is_member("th_1", "u1") is False


async def test_add_member_idempotent(store: PostgresChatStore) -> None:
    user = UserIdentity(id="u1", name="Alice")
    await store.add_member("th_1", user, added_by=user)
    await store.add_member("th_1", user, added_by=user)
    members = await store.list_members("th_1")
    assert len(members) == 1
