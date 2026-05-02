import pytest


def test_postgres_sink_import_requires_asyncpg() -> None:
    """Without asyncpg installed, importing the postgres module raises a friendly ImportError."""
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="asyncpg"):
            from rfnry_chat_client.telemetry.postgres import PostgresTelemetrySink  # noqa: F401
        return

    # If asyncpg IS installed (e.g. dev environment), import succeeds
    from rfnry_chat_client.telemetry.postgres import PostgresTelemetrySink

    assert PostgresTelemetrySink is not None
