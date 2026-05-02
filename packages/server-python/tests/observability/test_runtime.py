import pytest

from rfnry_chat_server.observability.record import ObservabilityRecord
from rfnry_chat_server.observability.runtime import Observability


class _Capture:
    def __init__(self) -> None:
        self.records: list[ObservabilityRecord] = []

    async def emit(self, record: ObservabilityRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_log_emits_record_with_metadata() -> None:
    sink = _Capture()
    obs = Observability(sink=sink)
    await obs.emit(
        "thread.create",
        message="created",
        level="info",
        scope_leaf="acme",
        thread_id="thr_1",
        worker_id="user_1",
        context={"members": 2},
    )
    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.kind == "thread.create"
    assert rec.scope_leaf == "acme"
    assert rec.thread_id == "thr_1"
    assert rec.worker_id == "user_1"
    assert rec.context == {"members": 2}


@pytest.mark.asyncio
async def test_log_drops_below_level() -> None:
    sink = _Capture()
    obs = Observability(sink=sink, level="warn")
    await obs.emit("debug.event", level="debug")
    await obs.emit("info.event", level="info")
    await obs.emit("warn.event", level="warn")
    await obs.emit("error.event", level="error")
    kinds = [r.kind for r in sink.records]
    assert kinds == ["warn.event", "error.event"]


@pytest.mark.asyncio
async def test_log_captures_error_metadata() -> None:
    sink = _Capture()
    obs = Observability(sink=sink)
    try:
        raise ValueError("boom")
    except ValueError as exc:
        await obs.emit("handler.error", level="error", error=exc)
    rec = sink.records[0]
    assert rec.error_type == "ValueError"
    assert rec.error_message == "boom"
    assert rec.traceback is not None
    assert "ValueError: boom" in rec.traceback


@pytest.mark.asyncio
async def test_log_suppresses_sink_failure() -> None:
    class _Broken:
        async def emit(self, record: ObservabilityRecord) -> None:
            raise RuntimeError("nope")

    obs = Observability(sink=_Broken())
    await obs.emit("anything")
