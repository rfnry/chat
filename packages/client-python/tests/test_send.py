from __future__ import annotations

from typing import Any

import pytest
from rfnry_chat_protocol import AssistantIdentity, Event, TextPart

from rfnry_chat_client.send import Send

_ME = AssistantIdentity(id="a_me", name="Me")


def _send(run_id: str | None = None) -> Send:
    return Send(thread_id="t_1", author=_ME, run_id=run_id)


class _RecordingClient:
    def __init__(self) -> None:
        self.emitted: list[Event] = []
        self.return_value: Event | None = None

    async def emit_event(self, event: Event) -> Event:
        self.emitted.append(event)
        return self.return_value if self.return_value is not None else event

    def __getattr__(self, _name: str) -> Any:
        raise AttributeError(_name)


def test_message_uses_supplied_author_and_thread() -> None:
    send = _send()
    evt = send.message([TextPart(text="hi")])
    assert evt.type == "message"
    assert evt.thread_id == "t_1"
    assert evt.author.id == "a_me"
    assert evt.run_id is None


def test_message_carries_run_id_when_set() -> None:
    send = _send(run_id="run_9")
    evt = send.message([TextPart(text="hi")])
    assert evt.run_id == "run_9"


def test_reasoning_shape() -> None:
    send = _send()
    evt = send.reasoning("thinking")
    assert evt.type == "reasoning"
    assert evt.content == "thinking"


def test_tool_call_generates_tool_id_by_default() -> None:
    send = _send()
    evt = send.tool_call("get_stock", {"ticker": "R"})
    assert evt.type == "tool.call"
    assert evt.tool.name == "get_stock"
    assert evt.tool.id.startswith("call_")


def test_tool_result_shape() -> None:
    send = _send()
    evt = send.tool_result("call_1", result={"ok": True})
    assert evt.type == "tool.result"
    assert evt.tool.id == "call_1"
    assert evt.tool.result == {"ok": True}


async def test_emit_forwards_to_client_emit_event() -> None:
    client = _RecordingClient()
    send = Send(thread_id="t_1", author=_ME, run_id="run_x", client=client)  # type: ignore[arg-type]
    event = send.message([TextPart(text="hi")])
    returned = await send.emit(event)
    assert client.emitted == [event]
    assert returned is event


async def test_emit_returns_what_client_returns() -> None:
    client = _RecordingClient()
    send = Send(thread_id="t_1", author=_ME, client=client)  # type: ignore[arg-type]
    sent = send.message([TextPart(text="x")])
    received = sent.model_copy(update={"id": "evt_normalized"})
    client.return_value = received
    result = await send.emit(sent)
    assert result is received


async def test_emit_raises_when_client_missing() -> None:
    send = Send(thread_id="t_1", author=_ME)
    with pytest.raises(RuntimeError, match="ChatClient"):
        await send.emit(send.message([TextPart(text="hi")]))
