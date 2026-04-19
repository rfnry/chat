from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from rfnry_chat_server.protocol.thread import Thread
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def store(clean_db: asyncpg.Pool) -> PostgresChatStore:
    return PostgresChatStore(pool=clean_db)


def _t(id: str, tenant: dict[str, str]) -> Thread:
    now = datetime.now(UTC)
    return Thread(id=id, tenant=tenant, metadata={}, created_at=now, updated_at=now)


async def test_list_subset_match(store: PostgresChatStore) -> None:
    await store.create_thread(_t("a", {"org": "A", "ws": "X"}))
    await store.create_thread(_t("b", {"org": "A", "ws": "Y"}))
    await store.create_thread(_t("c", {"org": "B", "ws": "X"}))
    await store.create_thread(_t("d", {}))

    page = await store.list_threads(tenant_filter={"org": "A"})
    ids = {t.id for t in page.items}
    assert ids == {"d"}

    page = await store.list_threads(tenant_filter={"org": "A", "ws": "X"})
    ids = {t.id for t in page.items}
    assert ids == {"a", "d"}

    page = await store.list_threads(tenant_filter={})
    ids = {t.id for t in page.items}
    assert ids == {"d"}


async def test_list_paginates(store: PostgresChatStore) -> None:
    for i in range(5):
        await store.create_thread(_t(f"t_{i}", {}))
    page = await store.list_threads(tenant_filter={}, limit=2)
    assert len(page.items) == 2
    assert page.next_cursor is not None

    page2 = await store.list_threads(tenant_filter={}, cursor=page.next_cursor, limit=2)
    assert len(page2.items) == 2
    assert {t.id for t in page.items}.isdisjoint({t.id for t in page2.items})
