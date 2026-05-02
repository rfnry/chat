import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rfnry_chat_server.observability.record import ObservabilityRecord
from rfnry_chat_server.observability.sink import (
    JsonlFileSink,
    JsonlStderrSink,
    MultiSink,
    NullSink,
    PrettyStderrSink,
    default_observability_sink,
)


def _record(**overrides: object) -> ObservabilityRecord:
    defaults: dict[str, object] = {
        "at": datetime.now(UTC),
        "level": "info",
        "kind": "test.event",
    }
    defaults.update(overrides)
    return ObservabilityRecord(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_jsonl_stderr_sink_writes_one_json_line() -> None:
    buf = io.StringIO()
    sink = JsonlStderrSink(stream=buf)
    await sink.emit(_record(message="hello"))
    line = buf.getvalue()
    assert line.endswith("\n")
    payload = json.loads(line)
    assert payload["kind"] == "test.event"
    assert payload["message"] == "hello"
    assert payload["schema_version"] == 1


@pytest.mark.asyncio
async def test_jsonl_file_sink_appends(tmp_path: Path) -> None:
    target = tmp_path / "logs" / "obs.log"
    sink = JsonlFileSink(path=target)
    await sink.emit(_record(message="one"))
    await sink.emit(_record(message="two"))
    lines = target.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["message"] == "one"
    assert json.loads(lines[1])["message"] == "two"


@pytest.mark.asyncio
async def test_multi_sink_fans_out_and_isolates_failure() -> None:
    captured: list[ObservabilityRecord] = []

    class _Capture:
        async def emit(self, record: ObservabilityRecord) -> None:
            captured.append(record)

    class _Broken:
        async def emit(self, record: ObservabilityRecord) -> None:
            raise RuntimeError("broken sink")

    multi = MultiSink(sinks=[_Broken(), _Capture()])
    await multi.emit(_record(message="x"))
    assert len(captured) == 1
    assert captured[0].message == "x"


@pytest.mark.asyncio
async def test_null_sink_silences() -> None:
    sink = NullSink()
    await sink.emit(_record(message="ignored"))


@pytest.mark.asyncio
async def test_pretty_stderr_sink_renders_human_line() -> None:
    buf = io.StringIO()
    sink = PrettyStderrSink(stream=buf, use_color=False)
    await sink.emit(
        _record(
            level="warn",
            kind="tool.error",
            scope_leaf="acme/u1",
            thread_id="thr_1",
            run_id="run_1",
            worker_id="market-bot",
            context={"tool": "news", "duration_ms": 18},
            error_type="HTTPStatusError",
            error_message="404",
        )
    )
    line = buf.getvalue()
    assert "WARN" in line
    assert "tool.error" in line
    assert "scope=acme/u1" in line
    assert "thread=thr_1" in line
    assert "run=run_1" in line
    assert "worker=market-bot" in line
    assert "tool=news" in line
    assert "duration_ms=18" in line
    assert "(HTTPStatusError: 404)" in line


def test_default_sink_picks_jsonl_when_no_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RFNRY_OBSERVABILITY_FORMAT", raising=False)
    monkeypatch.setattr("sys.stderr.isatty", lambda: False, raising=False)
    sink = default_observability_sink()
    assert isinstance(sink, JsonlStderrSink)


def test_default_sink_pretty_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RFNRY_OBSERVABILITY_FORMAT", "pretty")
    monkeypatch.delenv("NO_COLOR", raising=False)
    sink = default_observability_sink()
    assert isinstance(sink, PrettyStderrSink)
    assert sink.use_color is True


def test_default_sink_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RFNRY_OBSERVABILITY_FORMAT", "pretty")
    monkeypatch.setenv("NO_COLOR", "1")
    sink = default_observability_sink()
    assert isinstance(sink, PrettyStderrSink)
    assert sink.use_color is False


def test_default_sink_json_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RFNRY_OBSERVABILITY_FORMAT", "json")
    sink = default_observability_sink()
    assert isinstance(sink, JsonlStderrSink)
