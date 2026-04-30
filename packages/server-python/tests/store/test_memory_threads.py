from __future__ import annotations

import secrets
from datetime import UTC, datetime

import pytest
from rfnry_chat_protocol import Thread, UserIdentity
from rfnry_chat_protocol.content import TextPart
from rfnry_chat_protocol.event import MessageEvent

from rfnry_chat_server.store.memory.store import InMemoryChatStore


@pytest.fixture
def store() -> InMemoryChatStore:
    return InMemoryChatStore()


def _new_thread(id: str = "th_1") -> Thread:
    now = datetime.now(UTC)
    return Thread(id=id, tenant={}, metadata={}, created_at=now, updated_at=now)


async def test_find_thread_by_client_id_returns_match(store: InMemoryChatStore) -> None:
    await store.create_thread(_new_thread(id="th_1"), caller_identity_id="u_alice", client_id="ck-1")
    found = await store.find_thread_by_client_id("u_alice", "ck-1")
    assert found is not None
    assert found.id == "th_1"


async def test_find_thread_by_client_id_scoped_per_caller(store: InMemoryChatStore) -> None:
    await store.create_thread(_new_thread(id="th_1"), caller_identity_id="u_alice", client_id="ck-shared")
    await store.create_thread(_new_thread(id="th_2"), caller_identity_id="u_bob", client_id="ck-shared")
    alice_found = await store.find_thread_by_client_id("u_alice", "ck-shared")
    bob_found = await store.find_thread_by_client_id("u_bob", "ck-shared")
    assert alice_found is not None and alice_found.id == "th_1"
    assert bob_found is not None and bob_found.id == "th_2"


async def test_find_thread_by_client_id_returns_none_when_absent(
    store: InMemoryChatStore,
) -> None:
    await store.create_thread(_new_thread(id="th_1"))
    assert await store.find_thread_by_client_id("u_alice", "ck-nope") is None


async def test_create_thread_without_client_id_is_not_indexed(
    store: InMemoryChatStore,
) -> None:
    await store.create_thread(_new_thread(id="th_1"), caller_identity_id="u_alice")
    assert await store.find_thread_by_client_id("u_alice", "anything") is None


async def test_delete_thread_removes_client_id_entry(store: InMemoryChatStore) -> None:
    await store.create_thread(_new_thread(id="th_1"), caller_identity_id="u_alice", client_id="ck-1")
    await store.delete_thread("th_1")
    assert await store.find_thread_by_client_id("u_alice", "ck-1") is None


def _make_message(thread_id: str, author_id: str = "u_alice") -> MessageEvent:
    return MessageEvent(
        id=f"evt_{secrets.token_hex(8)}",
        thread_id=thread_id,
        author=UserIdentity(id=author_id, name=author_id, metadata={}),
        created_at=datetime.now(UTC),
        content=[TextPart(text="hi")],
    )


async def test_clear_events_wipes_thread_events(store: InMemoryChatStore) -> None:
    await store.create_thread(_new_thread(id="th_1"))
    await store.append_event(_make_message("th_1"))
    await store.append_event(_make_message("th_1"))
    page = await store.list_events("th_1")
    assert len(page.items) == 2

    await store.clear_events("th_1")
    page = await store.list_events("th_1")
    assert page.items == []


async def test_clear_events_keeps_thread_itself(store: InMemoryChatStore) -> None:
    await store.create_thread(_new_thread(id="th_1"))
    await store.append_event(_make_message("th_1"))
    await store.clear_events("th_1")
    assert await store.get_thread("th_1") is not None


async def test_clear_events_isolated_per_thread(store: InMemoryChatStore) -> None:
    await store.create_thread(_new_thread(id="th_1"))
    await store.create_thread(_new_thread(id="th_2"))
    await store.append_event(_make_message("th_1"))
    await store.append_event(_make_message("th_2"))

    await store.clear_events("th_1")
    assert (await store.list_events("th_1")).items == []
    assert len((await store.list_events("th_2")).items) == 1


async def test_clear_events_is_idempotent_on_empty_thread(
    store: InMemoryChatStore,
) -> None:
    await store.create_thread(_new_thread(id="th_1"))

    await store.clear_events("th_1")

    await store.clear_events("th_1")


async def test_clear_events_on_unknown_thread_is_noop(store: InMemoryChatStore) -> None:

    await store.clear_events("th_missing")
    await store.create_thread(_new_thread(id="th_missing"))
    await store.append_event(_make_message("th_missing"))
    assert len((await store.list_events("th_missing")).items) == 1
