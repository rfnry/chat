from rfnry_chat_server.observability import (
    JsonlFileSink,
    JsonlStderrSink,
    MultiSink,
    NullSink,
    Observability,
    ObservabilityLevel,
    ObservabilityRecord,
    ObservabilitySink,
    PrettyStderrSink,
    default_observability_sink,
)


def test_public_api() -> None:
    assert Observability is not None
    assert ObservabilityRecord is not None
    assert ObservabilitySink is not None
    assert ObservabilityLevel is not None
    assert JsonlStderrSink is not None
    assert JsonlFileSink is not None
    assert MultiSink is not None
    assert NullSink is not None
    assert PrettyStderrSink is not None
    assert default_observability_sink is not None
