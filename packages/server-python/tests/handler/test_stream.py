from __future__ import annotations

import pytest

from rfnry_chat_server.handler.send import HandlerSend
from rfnry_chat_server.handler.stream import StreamSink
from rfnry_chat_server.protocol.content import TextPart
from rfnry_chat_server.protocol.event import Event, MessageEvent
from rfnry_chat_server.protocol.identity import AssistantIdentity
from rfnry_chat_server.protocol.stream import StreamDeltaFrame, StreamEndFrame, StreamStartFrame


class _FakeSink:
    def __init__(self) -> None:
        self.starts: list[StreamStartFrame] = []
        self.deltas: list[StreamDeltaFrame] = []
        self.ends: list[StreamEndFrame] = []
        self.published: list[Event] = []

    async def start(self, frame: StreamStartFrame) -> None:
        self.starts.append(frame)

    async def delta(self, frame: StreamDeltaFrame) -> None:
        self.deltas.append(frame)

    async def end(self, frame: StreamEndFrame) -> None:
        self.ends.append(frame)

    async def publish_event(self, event: Event) -> Event:
        self.published.append(event)
        return event


def _send(sink: StreamSink) -> HandlerSend:
    return HandlerSend(
        thread_id="th_test",
        run_id="run_test",
        author=AssistantIdentity(id="asst", name="asst"),
        stream_sink=sink,
    )


async def test_message_stream_happy_path() -> None:
    sink = _FakeSink()
    send = _send(sink)

    async with send.message_stream() as stream:
        await stream.append("hello")
        await stream.append(" world")

    assert len(sink.starts) == 1
    assert [d.text for d in sink.deltas] == ["hello", " world"]
    assert len(sink.ends) == 1
    assert sink.ends[0].error is None
    assert len(sink.published) == 1

    event = sink.published[0]
    assert isinstance(event, MessageEvent)
    assert len(event.content) == 1
    part = event.content[0]
    assert isinstance(part, TextPart)
    assert part.text == "hello world"


async def test_message_stream_handler_error_publishes_no_event() -> None:
    sink = _FakeSink()
    send = _send(sink)

    with pytest.raises(RuntimeError):
        async with send.message_stream() as stream:
            await stream.append("partial")
            raise RuntimeError("boom")

    assert len(sink.starts) == 1
    assert len(sink.deltas) == 1
    assert len(sink.ends) == 1
    assert sink.ends[0].error is not None
    assert sink.ends[0].error.code == "handler_error"
    assert sink.published == []
