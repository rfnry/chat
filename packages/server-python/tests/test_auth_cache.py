from __future__ import annotations

import pytest
from rfnry_chat_protocol import UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.auth_cache import cached_authenticate


def _hs(token: str = "alice") -> HandshakeData:
    return HandshakeData(headers={"authorization": f"Bearer {token}"}, auth={})


async def test_cache_hit_avoids_underlying_call() -> None:

    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        return UserIdentity(id="u_alice", name="Alice")

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
    a = await wrapped(_hs())
    b = await wrapped(_hs())
    assert a is b
    assert calls == 1


async def test_cache_miss_for_different_token() -> None:

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

    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        return UserIdentity(id="u_alice", name="Alice")

    fake_now = [1000.0]
    monkeypatch.setattr(
        "rfnry_chat_server.auth_cache.time.monotonic",
        lambda: fake_now[0],
    )

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
    await wrapped(_hs())
    assert calls == 1

    fake_now[0] += 30.0
    await wrapped(_hs())
    assert calls == 1

    fake_now[0] += 31.0
    await wrapped(_hs())
    assert calls == 2


async def test_cache_lru_eviction_at_max_size() -> None:

    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        token = hs.headers["authorization"].removeprefix("Bearer ")
        return UserIdentity(id=f"u_{token}", name=token)

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0, max_size=2)
    await wrapped(_hs("a"))
    await wrapped(_hs("b"))
    await wrapped(_hs("a"))
    await wrapped(_hs("c"))

    assert calls == 3

    await wrapped(_hs("a"))
    assert calls == 3

    await wrapped(_hs("b"))
    assert calls == 4


async def test_cache_with_custom_key_function() -> None:

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

    calls = 0

    async def upstream(hs: HandshakeData) -> UserIdentity | None:
        nonlocal calls
        calls += 1
        return None

    wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
    no_auth_hs = HandshakeData(headers={}, auth={})
    await wrapped(no_auth_hs)
    await wrapped(no_auth_hs)
    assert calls == 2
