import asyncio

import pytest
from rfnry_chat_protocol import UserIdentity

from rfnry_chat_server.server.presence import PresenceRegistry


@pytest.mark.asyncio
async def test_first_socket_returns_true_then_false():
    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    assert await reg.add("u_a", "sid1", alice, tenant_path="/") is True
    assert await reg.add("u_a", "sid2", alice, tenant_path="/") is False


@pytest.mark.asyncio
async def test_last_socket_drop_returns_true():
    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    await reg.add("u_a", "sid1", alice, tenant_path="/")
    await reg.add("u_a", "sid2", alice, tenant_path="/")
    was_last, ident, tp = await reg.remove("u_a", "sid1")
    assert was_last is False
    assert ident is None
    was_last, ident, tp = await reg.remove("u_a", "sid2")
    assert was_last is True
    assert ident is not None and ident.id == "u_a"
    assert tp == "/"


@pytest.mark.asyncio
async def test_list_for_tenant_filters_by_path():
    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    bob = UserIdentity(id="u_b", name="Bob", metadata={})
    await reg.add("u_a", "sid1", alice, tenant_path="/A")
    await reg.add("u_b", "sid2", bob, tenant_path="/B")
    members_a = await reg.list_for_tenant("/A")
    members_b = await reg.list_for_tenant("/B")
    assert {m.id for m in members_a} == {"u_a"}
    assert {m.id for m in members_b} == {"u_b"}


@pytest.mark.asyncio
async def test_remove_unknown_sid_is_noop():
    reg = PresenceRegistry()
    was_last, ident, tp = await reg.remove("u_unknown", "sid_unknown")
    assert was_last is False
    assert ident is None
    assert tp is None


@pytest.mark.asyncio
async def test_concurrent_adds_yield_exactly_one_true():
    """50 parallel first-time adds for the same identity must produce exactly one True.

    This is the load-bearing invariant for broadcast correctness — without it,
    a refactor that drops the lock would let multiple connect handlers each
    fire `presence:joined` for the same socket.
    """
    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    results = await asyncio.gather(*[reg.add("u_a", f"sid{i}", alice, tenant_path="/") for i in range(50)])
    assert sum(1 for r in results if r is True) == 1


@pytest.mark.asyncio
async def test_concurrent_removes_yield_exactly_one_was_last():
    """50 parallel removes after 50 adds must produce exactly one was_last=True."""
    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    for i in range(50):
        await reg.add("u_a", f"sid{i}", alice, tenant_path="/")
    results = await asyncio.gather(*[reg.remove("u_a", f"sid{i}") for i in range(50)])
    assert sum(1 for was_last, _ident, _tp in results if was_last is True) == 1


@pytest.mark.asyncio
async def test_cross_tenant_re_add_is_rejected():
    """Same identity re-adding under a different tenant_path raises ValueError.

    In practice the auth layer prevents this — same Identity always derives
    the same tenant_path. The assertion exists so an upstream bug surfaces
    here rather than silently broadcasting `presence:left` on the wrong tenant.
    """
    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    await reg.add("u_a", "sid1", alice, tenant_path="/A")
    with pytest.raises(ValueError, match="tenant_path"):
        await reg.add("u_a", "sid2", alice, tenant_path="/B")
