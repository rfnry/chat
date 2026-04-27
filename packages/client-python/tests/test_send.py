from __future__ import annotations

from rfnry_chat_protocol import AssistantIdentity, TextPart

from rfnry_chat_client.send import Send

_ME = AssistantIdentity(id="a_me", name="Me")


def _send(run_id: str | None = None) -> Send:
    return Send(thread_id="t_1", author=_ME, run_id=run_id)


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
