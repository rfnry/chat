from datetime import UTC, datetime

from rfnry_chat_server.telemetry.record import TelemetryRow


def test_telemetry_row_schema_version_and_defaults() -> None:
    row = TelemetryRow(
        at=datetime.now(UTC),
        scope_leaf="acme/u1",
        thread_id="thr_1",
        run_id="run_1",
        actor_kind="user",
        actor_id="user_1",
        worker_id="user_1",
        triggered_by_id="user_1",
        status="completed",
    )
    assert row.schema_version == 1
    assert row.tokens_input == 0
    assert row.tokens_output == 0
    assert row.events_emitted == 0
    assert row.tool_calls == 0
    assert row.tool_errors == 0
    assert row.stream_deltas == 0
    assert row.duration_ms == 0
    assert row.provider is None
