from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from rfnry_chat_protocol import ThreadMember, UserIdentity

from rfnry_chat_server.members_cache import MembersCache


def _member(member_id: str, *, thread_id: str = "t1") -> ThreadMember:
    identity = UserIdentity(id=member_id, name=member_id.title())
    return ThreadMember(
        thread_id=thread_id,
        identity_id=identity.id,
        identity=identity,
        added_at=datetime.now(UTC),
        added_by=identity,
    )


class _FakeStore:
    def __init__(self, members: dict[str, list[ThreadMember]] | None = None) -> None:
        self.members = members or {}
        self.calls: list[str] = []
        self._gate: asyncio.Event | None = None

    async def list_members(self, thread_id: str) -> list[ThreadMember]:
        self.calls.append(thread_id)
        if self._gate is not None:
            await self._gate.wait()
        return list(self.members.get(thread_id, []))

    def __getattr__(self, _name: str) -> Any:
        raise AttributeError("only list_members is exercised in cache tests")


async def test_first_get_hits_store() -> None:
    store = _FakeStore({"t1": [_member("alice")]})
    cache = MembersCache(store, ttl_seconds=5.0)
    result = await cache.get("t1")
    assert [m.identity.id for m in result] == ["alice"]
    assert store.calls == ["t1"]


async def test_second_get_within_ttl_hits_cache() -> None:
    store = _FakeStore({"t1": [_member("alice")]})
    cache = MembersCache(store, ttl_seconds=5.0)
    await cache.get("t1")
    await cache.get("t1")
    assert store.calls == ["t1"]


async def test_get_after_invalidate_refetches() -> None:
    store = _FakeStore({"t1": [_member("alice")]})
    cache = MembersCache(store, ttl_seconds=5.0)
    await cache.get("t1")
    cache.invalidate("t1")
    await cache.get("t1")
    assert store.calls == ["t1", "t1"]


async def test_invalidate_isolates_per_thread() -> None:
    store = _FakeStore({"t1": [_member("alice")], "t2": [_member("bob", thread_id="t2")]})
    cache = MembersCache(store, ttl_seconds=5.0)
    await cache.get("t1")
    await cache.get("t2")
    cache.invalidate("t1")
    await cache.get("t1")
    await cache.get("t2")
    assert store.calls == ["t1", "t2", "t1"]


async def test_clear_drops_all_entries() -> None:
    store = _FakeStore({"t1": [_member("alice")], "t2": [_member("bob", thread_id="t2")]})
    cache = MembersCache(store, ttl_seconds=5.0)
    await cache.get("t1")
    await cache.get("t2")
    cache.clear()
    await cache.get("t1")
    await cache.get("t2")
    assert store.calls == ["t1", "t2", "t1", "t2"]


async def test_ttl_zero_disables_cache() -> None:
    store = _FakeStore({"t1": [_member("alice")]})
    cache = MembersCache(store, ttl_seconds=0.0)
    assert not cache.enabled
    await cache.get("t1")
    await cache.get("t1")
    assert store.calls == ["t1", "t1"]


async def test_negative_ttl_disables_cache() -> None:
    store = _FakeStore({"t1": [_member("alice")]})
    cache = MembersCache(store, ttl_seconds=-1.0)
    assert not cache.enabled
    await cache.get("t1")
    await cache.get("t1")
    assert store.calls == ["t1", "t1"]


async def test_ttl_expiry_refetches() -> None:
    store = _FakeStore({"t1": [_member("alice")]})
    cache = MembersCache(store, ttl_seconds=0.05)
    await cache.get("t1")
    await asyncio.sleep(0.1)
    await cache.get("t1")
    assert store.calls == ["t1", "t1"]


async def test_concurrent_misses_share_one_fetch() -> None:
    store = _FakeStore({"t1": [_member("alice")]})
    store._gate = asyncio.Event()
    cache = MembersCache(store, ttl_seconds=5.0)
    waiters = [asyncio.create_task(cache.get("t1")) for _ in range(5)]
    await asyncio.sleep(0.01)
    store._gate.set()
    results = await asyncio.gather(*waiters)
    assert all([m.identity.id for m in r] == ["alice"] for r in results)
    assert store.calls == ["t1"]


async def test_fetch_failure_propagates_and_does_not_cache() -> None:
    class _Boom(_FakeStore):
        async def list_members(self, thread_id: str) -> list[ThreadMember]:
            self.calls.append(thread_id)
            raise RuntimeError("db down")

    store = _Boom()
    cache = MembersCache(store, ttl_seconds=5.0)
    with pytest.raises(RuntimeError, match="db down"):
        await cache.get("t1")
    with pytest.raises(RuntimeError, match="db down"):
        await cache.get("t1")
    assert store.calls == ["t1", "t1"]


async def test_returned_list_mutation_does_not_affect_next_call() -> None:
    store = _FakeStore({"t1": [_member("alice")]})
    cache = MembersCache(store, ttl_seconds=5.0)
    first = await cache.get("t1")
    first.clear()
    second = await cache.get("t1")
    assert [m.identity.id for m in second] == ["alice"]
