from datetime import UTC, datetime

from rfnry_chat_client.observability.record import ObservabilityRecord


def test_observability_record_schema_version_default() -> None:
    record = ObservabilityRecord(
        at=datetime.now(UTC),
        level="info",
        kind="test.event",
    )
    assert record.schema_version == 1
    assert record.message == ""
    assert record.context == {}
    assert record.scope_leaf is None
