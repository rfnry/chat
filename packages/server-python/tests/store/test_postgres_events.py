from __future__ import annotations

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from rfnry_chat_protocol import MessageEvent, TextPart, Thread, UserIdentity

from rfnry_chat_server.store.postgres.store import PostgresChatStore
from rfnry_chat_server.store.types import EventCursor


@pytest.fixture
async def store(clean_db: asyncpg.Pool) -> PostgresChatStore:
    s = PostgresChatStore(pool=clean_db)
    now = datetime.now(UTC)
    await s.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    return s


def _msg(
    id: str,
    ts: datetime,
    text: str,
    *,
    recipients: list[str] | None = None,
) -> MessageEvent:
    return MessageEvent(
        id=id,
        thread_id="th_1",
        author=UserIdentity(id="u1", name="Alice"),
        created_at=ts,
        content=[TextPart(text=text)],
        recipients=recipients,
    )


async def test_append_and_get(store: PostgresChatStore) -> None:
    ts = datetime.now(UTC)
    e = _msg("evt_1", ts, "hi")
    appended = await store.append_event(e)
    assert appended.id == "evt_1"

    got = await store.get_event("evt_1")
    assert got is not None
    assert isinstance(got, MessageEvent)
    assert got.content[0].text == "hi"  # type: ignore[union-attr]


async def test_list_events_in_order(store: PostgresChatStore) -> None:
    base = datetime.now(UTC)
    for i in range(3):
        await store.append_event(_msg(f"e_{i}", base + timedelta(seconds=i), f"m{i}"))

    page = await store.list_events("th_1", limit=10)
    assert [e.id for e in page.items] == ["e_0", "e_1", "e_2"]


async def test_list_events_since_cursor(store: PostgresChatStore) -> None:
    base = datetime.now(UTC)
    for i in range(5):
        await store.append_event(_msg(f"e_{i}", base + timedelta(seconds=i), f"m{i}"))

    cursor = EventCursor(created_at=base + timedelta(seconds=1), id="e_1")
    page = await store.list_events("th_1", since=cursor, limit=10)
    assert [e.id for e in page.items] == ["e_2", "e_3", "e_4"]


async def test_list_events_filter_by_type(store: PostgresChatStore) -> None:
    await store.append_event(_msg("e_1", datetime.now(UTC), "hi"))
    page = await store.list_events("th_1", types=["thread.created"])
    assert page.items == []
    page = await store.list_events("th_1", types=["message"])
    assert len(page.items) == 1


async def test_recipients_round_trip(store: PostgresChatStore) -> None:
    ts = datetime.now(UTC)
    event = _msg("e_rcp", ts, "directed message", recipients=["ops-assistant"])
    appended = await store.append_event(event)
    assert appended.recipients == ["ops-assistant"]

    got = await store.get_event("e_rcp")
    assert got is not None
    assert got.recipients == ["ops-assistant"]

    page = await store.list_events("th_1")
    stored = page.items[-1]
    assert isinstance(stored, MessageEvent)
    assert stored.recipients == ["ops-assistant"]


async def test_recipients_none_round_trip(store: PostgresChatStore) -> None:
    ts = datetime.now(UTC)
    event = _msg("e_broadcast", ts, "broadcast message", recipients=None)
    appended = await store.append_event(event)
    assert appended.recipients is None

    got = await store.get_event("e_broadcast")
    assert got is not None
    assert got.recipients is None
