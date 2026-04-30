import asyncio

import pytest
from rfnry_chat_protocol import UserIdentity

from rfnry_chat_server.presence import PresenceRegistry


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

    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    results = await asyncio.gather(*[reg.add("u_a", f"sid{i}", alice, tenant_path="/") for i in range(50)])
    assert sum(1 for r in results if r is True) == 1


@pytest.mark.asyncio
async def test_concurrent_removes_yield_exactly_one_was_last():

    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    for i in range(50):
        await reg.add("u_a", f"sid{i}", alice, tenant_path="/")
    results = await asyncio.gather(*[reg.remove("u_a", f"sid{i}") for i in range(50)])
    assert sum(1 for was_last, _ident, _tp in results if was_last is True) == 1


@pytest.mark.asyncio
async def test_cross_tenant_re_add_is_rejected():

    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    await reg.add("u_a", "sid1", alice, tenant_path="/A")
    with pytest.raises(ValueError, match="tenant_path"):
        await reg.add("u_a", "sid2", alice, tenant_path="/B")
