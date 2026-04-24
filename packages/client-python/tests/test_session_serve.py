from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from rfnry_chat_protocol import UserIdentity

from rfnry_chat_client.client import ChatClient, _LifespanNoiseFilter  # noqa  (exposed for testing)


def _stub_client() -> ChatClient:
    """ChatClient with connect/disconnect stubbed — no real socket."""
    client = ChatClient(
        base_url="http://test.invalid",
        identity=UserIdentity(id="u_test", name="Test"),
    )
    client._socket = MagicMock()
    client._socket.connect = AsyncMock()
    client._socket.disconnect = AsyncMock()
    client._socket.on_raw_event = MagicMock()
    client._rest = MagicMock()
    client._rest.aclose = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_session_calls_on_connect_and_disconnect() -> None:
    client = _stub_client()
    calls: list[str] = []

    async def _on_connect() -> None:
        calls.append("on_connect")

    async with client.session(on_connect=_on_connect):
        # give the background task a chance to reach on_connect
        for _ in range(20):
            if "on_connect" in calls:
                break
            await asyncio.sleep(0.01)
        assert "on_connect" in calls

    # After exit: disconnect was called.
    client._socket.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_session_without_on_connect_still_works() -> None:
    client = _stub_client()
    async with client.session():
        await asyncio.sleep(0.05)
    client._socket.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_session_cancels_run_task_on_exit() -> None:
    client = _stub_client()

    async with client.session():
        pass  # immediate exit — task should be cleaned up

    # The run() task spun up internally must have been cancelled / completed.
    # We don't expose the task, but ensure no asyncio warnings about
    # never-awaited or pending. A sentinel check via gc of tasks is flaky;
    # instead, rely on the contract that session() blocks until cleanup.
    # Assert that after exit, a second session() works cleanly.
    async with client.session():
        pass


@pytest.mark.asyncio
async def test_session_installs_logging_filter() -> None:
    client = _stub_client()
    uvicorn_logger = logging.getLogger("uvicorn.error")

    async with client.session():
        filters = [type(f).__name__ for f in uvicorn_logger.filters]
        assert "_LifespanNoiseFilter" in filters


def test_lifespan_noise_filter_drops_cancelled_error() -> None:
    f = _LifespanNoiseFilter()
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Exception in 'lifespan' protocol\n",
        args=(),
        exc_info=(asyncio.CancelledError, asyncio.CancelledError(), None),
    )
    assert f.filter(record) is False


def test_lifespan_noise_filter_keeps_other_errors() -> None:
    f = _LifespanNoiseFilter()
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Some other error",
        args=(),
        exc_info=(ValueError, ValueError("x"), None),
    )
    assert f.filter(record) is True

    # Also keeps lifespan-protocol logs that aren't CancelledError
    record2 = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Exception in 'lifespan' protocol\n",
        args=(),
        exc_info=(ValueError, ValueError("x"), None),
    )
    assert f.filter(record2) is True


def test_serve_wraps_app_lifespan_and_calls_uvicorn_run(monkeypatch) -> None:
    """serve() should patch the app's lifespan with session + call uvicorn.run."""
    from fastapi import FastAPI

    client = _stub_client()
    # Pre-existing lifespan on the app
    original_called = {"entered": False, "exited": False}

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def original_lifespan(_app):
        original_called["entered"] = True
        try:
            yield
        finally:
            original_called["exited"] = True

    app = FastAPI(lifespan=original_lifespan)

    calls: dict = {}

    def fake_uvicorn_run(the_app, **kwargs):
        # Simulate uvicorn running: drive the lifespan to verify chaining.
        calls["app"] = the_app
        calls["kwargs"] = kwargs
        # Drive the (now-wrapped) lifespan manually
        import asyncio as _asyncio

        async def _drive():
            ctx = the_app.router.lifespan_context(the_app)
            await ctx.__aenter__()
            await ctx.__aexit__(None, None, None)

        _asyncio.run(_drive())

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    client.serve(app, host="127.0.0.1", port=9999)

    assert calls["app"] is app
    assert calls["kwargs"] == {"host": "127.0.0.1", "port": 9999}
    assert original_called["entered"] is True
    assert original_called["exited"] is True
    # disconnect should have been awaited during the wrapped lifespan exit
    client._socket.disconnect.assert_awaited()


def test_serve_catches_top_level_cancelled_error(monkeypatch) -> None:
    """If uvicorn.run raises CancelledError (the known post-shutdown quirk),
    serve() must not let it propagate."""
    from fastapi import FastAPI

    client = _stub_client()
    app = FastAPI()

    def fake_uvicorn_run(*a, **kw):
        raise asyncio.CancelledError()

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    # Should return cleanly, not raise.
    client.serve(app, host="127.0.0.1", port=9999)
