from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from rfnry_chat_protocol import (
    AssistantIdentity,
    Event,
    EventDraft,
    MessageEvent,
    ReasoningEvent,
    RunStartedEvent,
    TextPart,
    ThreadMemberAddedEvent,
    ToolCall,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
    UserIdentity,
    parse_event,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_message_event_with_text_part() -> None:
    e = MessageEvent(
        id="evt_1",
        thread_id="th_1",
        author=UserIdentity(id="u1", name="Alice"),
        created_at=_now(),
        content=[TextPart(text="hi")],
    )
    assert e.type == "message"
    assert len(e.content) == 1


def test_tool_call_event_payload_shape() -> None:
    e = ToolCallEvent(
        id="evt_2",
        thread_id="th_1",
        author=AssistantIdentity(id="a1", name="Helper"),
        created_at=_now(),
        tool=ToolCall(id="call_1", name="search", arguments={"q": "weather"}),
    )
    assert e.tool.id == "call_1"
    assert e.tool.arguments == {"q": "weather"}


def test_tool_result_symmetric_with_call() -> None:
    e = ToolResultEvent(
        id="evt_3",
        thread_id="th_1",
        author=AssistantIdentity(id="a1", name="Helper"),
        created_at=_now(),
        tool=ToolResult(id="call_1", result={"temp": 72}),
    )
    assert e.tool.id == "call_1"
    assert e.tool.result == {"temp": 72}


def test_thread_member_added_event() -> None:
    me = AssistantIdentity(id="a1", name="Helper")
    user = UserIdentity(id="u2", name="Bob")
    e = ThreadMemberAddedEvent(
        id="evt_4",
        thread_id="th_1",
        author=me,
        created_at=_now(),
        member=user,
    )
    assert e.member.id == "u2"


def test_run_started_event() -> None:
    e = RunStartedEvent(
        id="evt_5",
        thread_id="th_1",
        author=AssistantIdentity(id="a1", name="Helper"),
        created_at=_now(),
        run_id="run_1",
    )
    assert e.run_id == "run_1"


def test_parse_event_dispatches_on_type() -> None:
    raw = {
        "id": "evt_1",
        "thread_id": "th_1",
        "author": {"role": "user", "id": "u1", "name": "Alice", "metadata": {}},
        "created_at": _now().isoformat(),
        "metadata": {},
        "type": "message",
        "content": [{"type": "text", "text": "hi"}],
    }
    parsed: Event = parse_event(raw)
    assert isinstance(parsed, MessageEvent)


def test_event_draft_minimum() -> None:
    d = EventDraft(client_id="cid_1", content=[TextPart(text="hi")])
    assert d.client_id == "cid_1"
    assert d.metadata == {}


def test_event_draft_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EventDraft(  # type: ignore[call-arg]
            client_id="cid_1",
            content=[TextPart(text="hi")],
            author={"id": "fake", "name": "fake", "role": "user"},
        )


def test_reasoning_event_text_only() -> None:
    e = ReasoningEvent(
        id="evt_6",
        thread_id="th_1",
        author=AssistantIdentity(id="a1", name="Helper"),
        created_at=_now(),
        content="Thinking...",
    )
    assert e.content == "Thinking..."
