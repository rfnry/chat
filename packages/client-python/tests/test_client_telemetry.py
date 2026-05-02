from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

from rfnry_chat_protocol import AssistantIdentity, TextPart, UserIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.handler.dispatcher import HandlerDispatcher
from rfnry_chat_client.observability import NullSink, Observability
from rfnry_chat_client.send import Send
from rfnry_chat_client.telemetry import (
    SqliteTelemetrySink,
    Telemetry,
    TelemetryRow,
)


class _Capture:
    def __init__(self) -> None:
        self.rows: list[TelemetryRow] = []

    async def write(self, row: TelemetryRow) -> None:
        self.rows.append(row)


class _StubClient:
    def __init__(self, telemetry: Telemetry) -> None:
        self.emitted: list[Any] = []
        self._next_run_id = 0
        self.observability = Observability(sink=NullSink())
        self.telemetry = telemetry

    async def emit_event(self, event: Any) -> Any:
        self.emitted.append(event)
        return event

    @property
    def socket(self) -> Any:
        return self

    async def begin_run(self, _thread_id: str, **_kwargs: Any) -> dict[str, Any]:
        self._next_run_id += 1
        return {"run_id": f"run_{self._next_run_id}", "status": "running"}

    async def end_run(self, run_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"run_id": run_id, "status": "completed"}


_event_id_seq = itertools.count(1)


def _msg(*, author_id: str = "u_other", recipients: list[str] | None = None) -> dict[str, Any]:
    author = {"role": "user", "id": author_id, "name": author_id, "metadata": {}}
    return {
        "id": f"evt_{next(_event_id_seq)}",
        "thread_id": "t_1",
        "run_id": None,
        "author": author,
        "created_at": datetime.now(UTC).isoformat(),
        "metadata": {},
        "client_id": None,
        "recipients": recipients,
        "type": "message",
        "content": [{"type": "text", "text": "hi"}],
    }


def test_chat_client_default_telemetry_attached() -> None:
    client = ChatClient(base_url="http://example.invalid", identity=UserIdentity(id="u", name="u"))
    assert isinstance(client.telemetry, Telemetry)


def test_chat_client_data_root_auto_wires_sqlite_sink(tmp_path) -> None:
    client = ChatClient(
        base_url="http://example.invalid",
        identity=UserIdentity(id="u", name="u"),
        data_root=tmp_path,
    )
    assert isinstance(client.telemetry.sink, SqliteTelemetrySink)


def test_chat_client_explicit_telemetry_wins(tmp_path) -> None:
    sink = _Capture()
    explicit = Telemetry(sink=sink)
    client = ChatClient(
        base_url="http://example.invalid",
        identity=UserIdentity(id="u", name="u"),
        data_root=tmp_path,
        telemetry=explicit,
    )
    assert client.telemetry is explicit


async def test_failing_emitter_handler_writes_telemetry_row_with_failed_status() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    capture = _Capture()
    telemetry = Telemetry(sink=capture)
    client = _StubClient(telemetry=telemetry)
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def boom(_ctx: HandlerContext, send: Send):
        yield send.message(content=[TextPart(text="hi")])
        yield send.message(content=[TextPart(text="bye")])
        raise RuntimeError("kaboom")

    dispatcher.register("message", boom)
    try:
        await dispatcher.feed(_msg(author_id="u_other"))
    except RuntimeError:
        pass

    assert len(capture.rows) == 1
    row = capture.rows[0]
    assert row.status == "failed"
    assert row.error_code == "handler_error"
    assert row.error_message == "kaboom"
    assert row.events_emitted == 2
    assert row.tool_calls == 0
    assert row.tool_errors == 0
    assert row.actor_kind == "assistant"
    assert row.actor_id == "a_me"
    assert row.worker_id == "a_me"
    assert row.triggered_by_id == "u_other"
    assert row.thread_id == "t_1"
    assert row.run_id == "run_1"


async def test_successful_emitter_handler_writes_completed_telemetry_row() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    capture = _Capture()
    telemetry = Telemetry(sink=capture)
    client = _StubClient(telemetry=telemetry)
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def reply(_ctx: HandlerContext, send: Send):
        yield send.message(content=[TextPart(text="hi")])

    dispatcher.register("message", reply)
    await dispatcher.feed(_msg(author_id="u_other"))

    assert len(capture.rows) == 1
    row = capture.rows[0]
    assert row.status == "completed"
    assert row.error_code is None
    assert row.error_message is None
    assert row.events_emitted == 1
    assert row.tool_calls == 0
    assert row.actor_kind == "assistant"
