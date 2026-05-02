def test_postgres_sink_imports() -> None:
    from rfnry_chat_server.telemetry.postgres import PostgresTelemetrySink

    assert PostgresTelemetrySink is not None
