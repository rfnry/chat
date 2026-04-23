from __future__ import annotations

import pytest
from rfnry_chat_protocol import UserIdentity

from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.auth_cache import cached_authenticate


def _hs(token: str = "alice") -> HandshakeData:
    return HandshakeData(headers={"authorization": f"Bearer {token}"}, auth={})


async def test_cache_hit_avoids_underlying_call() -> None:
    """A second call with the same token must NOT re-invoke the wrapped callback."""
    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        return UserIdentity(id="u_alice", name="Alice")

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
    a = await wrapped(_hs())
    b = await wrapped(_hs())
    assert a is b  # cached object reference returned
    assert calls == 1


async def test_cache_miss_for_different_token() -> None:
    """Different Authorization headers produce independent cache entries."""
    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        token = hs.headers["authorization"].removeprefix("Bearer ")
        return UserIdentity(id=f"u_{token}", name=token)

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
    a = await wrapped(_hs("alice"))
    b = await wrapped(_hs("bob"))
    assert a is not None and a.id == "u_alice"
    assert b is not None and b.id == "u_bob"
    assert calls == 2


async def test_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry past its TTL must trigger a fresh upstream call."""
    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        return UserIdentity(id="u_alice", name="Alice")

    fake_now = [1000.0]
    monkeypatch.setattr(
        "rfnry_chat_server.server.auth_cache.time.monotonic",
        lambda: fake_now[0],
    )

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
    await wrapped(_hs())
    assert calls == 1

    fake_now[0] += 30.0  # within TTL
    await wrapped(_hs())
    assert calls == 1

    fake_now[0] += 31.0  # total elapsed: 61s — past TTL
    await wrapped(_hs())
    assert calls == 2


async def test_cache_lru_eviction_at_max_size() -> None:
    """Cache evicts least-recently-used entries when at capacity."""
    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        token = hs.headers["authorization"].removeprefix("Bearer ")
        return UserIdentity(id=f"u_{token}", name=token)

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0, max_size=2)
    await wrapped(_hs("a"))  # cache: {a}
    await wrapped(_hs("b"))  # cache: {a, b}
    await wrapped(_hs("a"))  # cache: {b, a} — touches a
    await wrapped(_hs("c"))  # cache: {a, c} — evicts b (LRU)

    assert calls == 3  # a, b, c upstream calls so far

    # Re-fetching a should hit cache (still present)
    await wrapped(_hs("a"))
    assert calls == 3

    # Re-fetching b should miss cache (was evicted)
    await wrapped(_hs("b"))
    assert calls == 4


async def test_cache_with_custom_key_function() -> None:
    """Consumers can override the cache key (e.g. cookie-based auth)."""
    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        return UserIdentity(id="u_alice", name="Alice")

    wrapped = cached_authenticate(
        upstream,
        ttl_seconds=60.0,
        key=lambda hs: str(hs.auth.get("session_id", "")),
    )
    hs1 = HandshakeData(headers={}, auth={"session_id": "s1"})
    hs2 = HandshakeData(headers={}, auth={"session_id": "s1"})
    await wrapped(hs1)
    await wrapped(hs2)
    assert calls == 1


async def test_cache_caches_none_too() -> None:
    """Failed auth (returns None) must also be cached so attackers can't
    brute-force token validity by timing or rate."""
    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        return None

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
    a = await wrapped(_hs("bad"))
    b = await wrapped(_hs("bad"))
    assert a is None
    assert b is None
    assert calls == 1


async def test_empty_key_bypasses_cache() -> None:
    """If the cache key function returns an empty string (e.g. no auth header),
    bypass the cache entirely so unauthenticated requests don't share a single
    cached entry."""
    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        return None

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
    no_auth_hs = HandshakeData(headers={}, auth={})  # no Authorization header
    await wrapped(no_auth_hs)
    await wrapped(no_auth_hs)
    assert calls == 2  # bypassed cache; upstream called both times
