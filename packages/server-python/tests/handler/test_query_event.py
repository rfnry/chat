from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from rfnry_chat_protocol import AssistantIdentity, Event, MessageEvent, Run, TextPart, Thread, UserIdentity

from rfnry_chat_server.analytics.collector import AssistantAnalytics
from rfnry_chat_server.handler.context import HandlerContext
from rfnry_chat_server.store.protocol import ChatStore
from rfnry_chat_server.store.types import Page


class _FakeStore:
    """Minimal ChatStore fake that only implements list_events.

    query_event() doesn't touch anything else, so we don't need to stand
    up Postgres for this test.
    """

    def __init__(self, events: list[Event]) -> None:
        self._events = events

    async def list_events(
        self,
        thread_id: str,
        since: Any = None,
        until: Any = None,
        limit: int = 100,
        types: Any = None,
    ) -> Page[Event]:
        # Return oldest-first, matching the real PostgresChatStore contract.
        return Page[Event](items=list(self._events[:limit]), next_cursor=None)


def _message(
    *,
    id: str,
    author_id: str,
    author_role: str,
    text: str,
    minutes_ago: int,
) -> MessageEvent:
    return MessageEvent(
        id=id,
        thread_id="t_test",
        author=(
            UserIdentity(id=author_id, name=author_id, metadata={})
            if author_role == "user"
            else AssistantIdentity(id=author_id, name=author_id, metadata={})
        ),
        created_at=datetime.now(UTC).replace(microsecond=minutes_ago * 1000),
        content=[TextPart(text=text)],
    )


def _message_with_recipients(
    *,
    id: str,
    author_id: str,
    recipients: list[str],
    text: str,
    minutes_ago: int,
) -> MessageEvent:
    return MessageEvent(
        id=id,
        thread_id="t_test",
        author=UserIdentity(id=author_id, name=author_id, metadata={}),
        created_at=datetime.now(UTC).replace(microsecond=minutes_ago * 1000),
        content=[TextPart(text=text)],
        recipients=recipients,
    )


def _build_ctx(events: list[Event], triggerer_id: str, assistant_id: str = "ops-assistant") -> HandlerContext:
    store = cast(ChatStore, _FakeStore(events))
    thread = Thread(
        id="t_test",
        tenant={"location": "warehouse_a"},
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assistant = AssistantIdentity(id=assistant_id, name="Ops Assistant", metadata={})
    run = Run(
        id="r_1",
        thread_id="t_test",
        actor=assistant,
        triggered_by=UserIdentity(id=triggerer_id, name=triggerer_id, metadata={}),
        status="running",
        started_at=datetime.now(UTC),
    )
    analytics = AssistantAnalytics(
        on_analytics=None,
        thread_id="t_test",
        run_id="r_1",
        assistant_id=assistant_id,
    )
    return HandlerContext(store=store, thread=thread, run=run, assistant=assistant, analytics=analytics)


async def test_query_event_returns_none_when_no_triggerer_message() -> None:
    events: list[Event] = [
        _message(id="e1", author_id="u_bob", author_role="user", text="bob's note", minutes_ago=3),
        _message(id="e2", author_id="u_carol", author_role="user", text="carol's note", minutes_ago=2),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice")
    assert await ctx.query_event() is None


async def test_query_event_returns_simple_latest_message() -> None:
    events: list[Event] = [
        _message(id="e1", author_id="u_alice", author_role="user", text="first", minutes_ago=3),
        _message(id="e2", author_id="u_alice", author_role="user", text="second", minutes_ago=2),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice")
    result = await ctx.query_event()
    assert result is not None
    assert result.id == "e2"
    assert result.content[0].text == "second"  # type: ignore[union-attr]


async def test_query_event_skips_team_chat_from_other_users() -> None:
    # Alice asks a question, then Bob posts team chat that lands right before
    # Alice's invoke fires. query_event must walk past Bob's message and
    # return Alice's, not events[-1].
    events: list[Event] = [
        _message(id="e1", author_id="u_alice", author_role="user", text="what is the valve spec", minutes_ago=5),
        _message(id="e2", author_id="u_bob", author_role="user", text="I'll check the drawings", minutes_ago=2),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice")
    result = await ctx.query_event()
    assert result is not None
    assert result.id == "e1"
    assert result.content[0].text == "what is the valve spec"  # type: ignore[union-attr]


async def test_query_event_ignores_assistant_replies() -> None:
    # The triggerer is a user, but we should not accidentally pick the
    # assistant's reply if the assistant id happens to match something weird.
    events: list[Event] = [
        _message(id="e1", author_id="u_alice", author_role="user", text="question", minutes_ago=4),
        _message(id="e2", author_id="ops-assistant", author_role="assistant", text="answer", minutes_ago=3),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice")
    result = await ctx.query_event()
    assert result is not None
    assert result.id == "e1"


async def test_events_relevant_to_me_filters_by_recipients() -> None:
    events: list[Event] = [
        _message(id="e1", author_id="u_alice", author_role="user", text="broadcast", minutes_ago=5),
        _message_with_recipients(
            id="e2",
            author_id="u_alice",
            recipients=["ops-assistant"],
            text="for specialist",
            minutes_ago=4,
        ),
        _message_with_recipients(
            id="e3",
            author_id="u_alice",
            recipients=["other-assistant"],
            text="for other",
            minutes_ago=3,
        ),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice", assistant_id="ops-assistant")

    all_events = await ctx.events(limit=10)
    assert len(all_events) == 3

    relevant = await ctx.events(limit=10, relevant_to_me=True)
    relevant_ids = [e.id for e in relevant]
    assert "e1" in relevant_ids
    assert "e2" in relevant_ids
    assert "e3" not in relevant_ids


async def test_query_event_uses_prefetched_events_without_hitting_store() -> None:
    # The store has NO matching message for u_alice. If query_event used
    # the store, it'd return None. We pass a pre-fetched events list that
    # does contain u_alice, so query_event should walk that list and
    # return the match — proving the store was not consulted.
    store_events: list[Event] = [
        _message(id="e_bob", author_id="u_bob", author_role="user", text="in the store", minutes_ago=5),
    ]
    prefetched: list[Event] = [
        _message(id="e_alice", author_id="u_alice", author_role="user", text="prefetched", minutes_ago=1),
    ]
    ctx = _build_ctx(store_events, triggerer_id="u_alice")
    result = await ctx.query_event(events=prefetched)
    assert result is not None
    assert result.id == "e_alice"
    assert result.content[0].text == "prefetched"  # type: ignore[union-attr]
