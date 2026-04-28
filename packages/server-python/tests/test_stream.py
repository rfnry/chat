from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from rfnry_chat_protocol import (
    AssistantIdentity,
    StreamDeltaFrame,
    StreamEndFrame,
    StreamStartFrame,
    Thread,
    UserIdentity,
)

from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.stream import Stream

ME = AssistantIdentity(id="a_me", name="Me")


class _StubServer:
    def __init__(self) -> None:
        self.broadcaster = RecordingBroadcaster()
        self.published: list[Any] = []
        self.namespace_keys = None

    def namespace_for_thread(self, _thread: Thread) -> str | None:
        return None

    async def broadcast_stream_start(self, frame: StreamStartFrame, *, thread: Thread) -> None:
        await self.broadcaster.broadcast_stream_start(frame, namespace=None)

    async def broadcast_stream_delta(self, frame: StreamDeltaFrame, *, thread: Thread) -> None:
        await self.broadcaster.broadcast_stream_delta(frame, namespace=None)

    async def broadcast_stream_end(self, frame: StreamEndFrame, *, thread: Thread) -> None:
        await self.broadcaster.broadcast_stream_end(frame, namespace=None)

    async def publish_event(self, event: Any, *, thread: Thread | None = None) -> Any:
        self.published.append(event)
        return event


def _thread() -> Thread:
    now = datetime.now(UTC)
    return Thread(id="t_1", tenant={}, metadata={}, created_at=now, updated_at=now)


def _stream(server: _StubServer, *, target_type: str = "message", **kwargs: Any) -> Stream:
    return Stream(
        server=server,  # type: ignore[arg-type]
        thread=_thread(),
        run_id="run_x",
        author=ME,
        target_type=target_type,  # type: ignore[arg-type]
        **kwargs,
    )


async def test_stream_lifecycle_emits_start_delta_end_and_finalized_event() -> None:
    server = _StubServer()
    async with _stream(server) as s:
        await s.write("hello")
        await s.write(" world")

    rec = server.broadcaster
    assert len(rec.stream_starts) == 1
    assert len(rec.stream_deltas) == 2
    assert rec.stream_deltas[0].text == "hello"
    assert rec.stream_deltas[1].text == " world"
    assert len(rec.stream_ends) == 1
    assert rec.stream_ends[0].error is None

    assert len(server.published) == 1
    final = server.published[0]
    assert final.type == "message"
    assert final.content[0].text == "hello world"


async def test_stream_error_exit_emits_end_with_error_and_skips_final_event() -> None:
    server = _StubServer()
    with pytest.raises(RuntimeError, match="boom"):
        async with _stream(server) as s:
            await s.write("partial")
            raise RuntimeError("boom")

    rec = server.broadcaster
    assert rec.stream_ends[0].error is not None
    assert rec.stream_ends[0].error.code == "stream_error"
    assert "boom" in rec.stream_ends[0].error.message
    assert server.published == []


async def test_stream_error_code_overrideable() -> None:
    server = _StubServer()
    with pytest.raises(RuntimeError, match="boom"):
        async with _stream(server, error_code="handler_error") as s:
            await s.write("x")
            raise RuntimeError("boom")
    assert server.broadcaster.stream_ends[0].error.code == "handler_error"


async def test_reasoning_stream_finalizes_as_reasoning_event() -> None:
    server = _StubServer()
    async with _stream(server, target_type="reasoning") as s:
        await s.write("thinking")
    final = server.published[0]
    assert final.type == "reasoning"
    assert final.content == "thinking"


async def test_stream_recipients_propagated_to_finalized_event() -> None:
    server = _StubServer()
    async with _stream(server, recipients=["u_alice"]) as s:
        await s.write("hi")
    final = server.published[0]
    assert final.recipients == ["u_alice"]


async def test_stream_event_id_unique_per_stream() -> None:
    server = _StubServer()
    async with _stream(server) as a:
        await a.write("a")
    async with _stream(server) as b:
        await b.write("b")
    ids = {e.id for e in server.published}
    assert len(ids) == 2


async def test_stream_write_before_enter_raises() -> None:
    server = _StubServer()
    s = _stream(server)
    with pytest.raises(RuntimeError, match="before"):
        await s.write("x")


async def test_send_message_stream_requires_server_and_thread() -> None:
    from rfnry_chat_server.send import Send

    bare = Send(thread_id="t_1", author=ME, run_id="run_x")
    with pytest.raises(RuntimeError, match="ChatServer"):
        bare.message_stream()

    no_thread = Send(thread_id="t_1", author=ME, run_id="run_x", server=_StubServer())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="thread"):
        no_thread.message_stream()


async def test_send_message_stream_requires_run_id() -> None:
    from rfnry_chat_server.send import Send

    server = _StubServer()
    no_run = Send(thread_id="t_1", author=UserIdentity(id="u", name="U"), server=server, thread=_thread())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="run_id"):
        no_run.message_stream()
