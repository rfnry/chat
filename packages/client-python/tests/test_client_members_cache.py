from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rfnry_chat_protocol import AssistantIdentity, Identity, ThreadMember, UserIdentity

from rfnry_chat_client.client import ChatClient

ME = AssistantIdentity(id="a_me", name="Me")
ALICE = UserIdentity(id="u_alice", name="Alice")


def _member(identity: Identity, thread_id: str) -> ThreadMember:
    return ThreadMember(
        thread_id=thread_id,
        identity_id=identity.id,
        identity=identity,
        added_at=datetime.now(UTC),
        added_by=identity,
    )


class _StubSocket:
    async def join_thread(self, thread_id: str, since: dict[str, str] | None = None) -> dict[str, Any]:
        return {"thread_id": thread_id, "replayed": [], "replay_truncated": False}


class _StubRest:
    def __init__(self) -> None:
        self.list_members_calls: list[str] = []
        self.add_member_calls: list[tuple[str, str]] = []
        self.remove_member_calls: list[tuple[str, str]] = []
        self.members_by_thread: dict[str, list[ThreadMember]] = {}

    async def list_members(self, thread_id: str) -> list[ThreadMember]:
        self.list_members_calls.append(thread_id)
        return list(self.members_by_thread.get(thread_id, []))

    async def add_member(self, thread_id: str, *, identity: Identity, role: str = "member") -> ThreadMember:
        self.add_member_calls.append((thread_id, identity.id))
        m = _member(identity, thread_id)
        self.members_by_thread.setdefault(thread_id, []).append(m)
        return m

    async def remove_member(self, thread_id: str, identity_id: str) -> None:
        self.remove_member_calls.append((thread_id, identity_id))
        existing = self.members_by_thread.get(thread_id, [])
        self.members_by_thread[thread_id] = [m for m in existing if m.identity_id != identity_id]


def _client(rest: _StubRest, *, ttl: float = 5.0) -> ChatClient:
    socket = _StubSocket()

    async def auth() -> dict[str, Any]:
        return {}

    c = ChatClient(
        base_url="http://test",
        identity=ME,
        authenticate=auth,
        socket_transport=socket,  # type: ignore[arg-type]
        member_cache_ttl_seconds=ttl,
    )
    c._rest = rest  # type: ignore[assignment]
    c._members_cache._rest = rest  # type: ignore[attr-defined]
    return c


async def test_list_members_caches_within_ttl() -> None:
    rest = _StubRest()
    rest.members_by_thread["t_1"] = [_member(ALICE, "t_1")]
    client = _client(rest)
    a = await client.list_members("t_1")
    b = await client.list_members("t_1")
    assert [m.identity.id for m in a] == ["u_alice"]
    assert [m.identity.id for m in b] == ["u_alice"]
    assert rest.list_members_calls == ["t_1"]


async def test_add_member_invalidates_cache() -> None:
    rest = _StubRest()
    rest.members_by_thread["t_1"] = [_member(ALICE, "t_1")]
    client = _client(rest)
    await client.list_members("t_1")
    assert rest.list_members_calls == ["t_1"]

    bob = UserIdentity(id="u_bob", name="Bob")
    await client.add_member("t_1", bob)
    members = await client.list_members("t_1")
    assert {m.identity.id for m in members} == {"u_alice", "u_bob"}
    assert rest.list_members_calls == ["t_1", "t_1"]


async def test_remove_member_invalidates_cache() -> None:
    rest = _StubRest()
    rest.members_by_thread["t_1"] = [_member(ALICE, "t_1")]
    client = _client(rest)
    await client.list_members("t_1")
    assert rest.list_members_calls == ["t_1"]

    await client.remove_member("t_1", "u_alice")
    members = await client.list_members("t_1")
    assert members == []
    assert rest.list_members_calls == ["t_1", "t_1"]


async def test_members_updated_frame_invalidates_cache() -> None:
    rest = _StubRest()
    rest.members_by_thread["t_1"] = [_member(ALICE, "t_1")]
    client = _client(rest)
    await client.list_members("t_1")
    assert rest.list_members_calls == ["t_1"]

    await client._on_members_updated_frame({"thread_id": "t_1", "members": []})
    await client.list_members("t_1")
    assert rest.list_members_calls == ["t_1", "t_1"]


async def test_members_updated_frame_only_invalidates_named_thread() -> None:
    rest = _StubRest()
    rest.members_by_thread["t_1"] = [_member(ALICE, "t_1")]
    rest.members_by_thread["t_2"] = [_member(ALICE, "t_2")]
    client = _client(rest)
    await client.list_members("t_1")
    await client.list_members("t_2")
    assert rest.list_members_calls == ["t_1", "t_2"]

    await client._on_members_updated_frame({"thread_id": "t_1", "members": []})
    await client.list_members("t_1")
    await client.list_members("t_2")
    assert rest.list_members_calls == ["t_1", "t_2", "t_1"]


async def test_invalidate_members_cache_public_method() -> None:
    rest = _StubRest()
    rest.members_by_thread["t_1"] = [_member(ALICE, "t_1")]
    client = _client(rest)
    await client.list_members("t_1")
    client.invalidate_members_cache("t_1")
    await client.list_members("t_1")
    assert rest.list_members_calls == ["t_1", "t_1"]
