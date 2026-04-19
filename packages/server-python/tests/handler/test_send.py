from rfnry_chat_server.handler.send import HandlerSend
from rfnry_chat_server.protocol.content import TextPart
from rfnry_chat_server.protocol.identity import AssistantIdentity


def _send() -> HandlerSend:
    return HandlerSend(
        thread_id="th_1",
        run_id="run_1",
        author=AssistantIdentity(id="a1", name="Helper"),
    )


def test_message_factory() -> None:
    e = _send().message(content=[TextPart(text="hi")])
    assert e.type == "message"
    assert e.thread_id == "th_1"
    assert e.run_id == "run_1"
    assert e.author.id == "a1"


def test_reasoning_factory() -> None:
    e = _send().reasoning("thinking")
    assert e.type == "reasoning"
    assert e.content == "thinking"


def test_tool_call_factory() -> None:
    e = _send().tool_call(name="search", arguments={"q": "x"})
    assert e.type == "tool.call"
    assert e.tool.name == "search"
    assert e.tool.id.startswith("call_")


def test_tool_result_factory() -> None:
    e = _send().tool_result(tool_id="call_1", result={"ok": True})
    assert e.type == "tool.result"
    assert e.tool.id == "call_1"
    assert e.tool.result == {"ok": True}
