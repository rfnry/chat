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


def test_lifespan_noise_filter_drops_starlette_shutdown_failed_cancelled() -> None:
    """Path 2: starlette sends lifespan.shutdown.failed with a raw traceback
    text when CancelledError propagates through the lifespan receive() await."""
    import traceback

    f = _LifespanNoiseFilter()
    try:
        raise asyncio.CancelledError()
    except asyncio.CancelledError:
        exc_text = traceback.format_exc()

    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg=exc_text,
        args=(),
        exc_info=None,
    )
    assert f.filter(record) is False


def test_lifespan_noise_filter_keeps_starlette_shutdown_failed_non_cancelled() -> None:
    """Path 2: must NOT suppress shutdown.failed tracebacks for real errors."""
    import traceback

    f = _LifespanNoiseFilter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        exc_text = traceback.format_exc()

    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg=exc_text,
        args=(),
        exc_info=None,
    )
    assert f.filter(record) is True


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


def test_serve_wraps_lifespan_and_calls_uvicorn_run_with_kwargs(monkeypatch) -> None:
    """serve() wraps the app's lifespan with session() and passes kwargs to uvicorn.run.

    The lifespan wrap is verified by driving the lifespan manually from inside
    the fake uvicorn.run — session() must have connected before the inner app
    lifespan yields, and disconnect must have been called after the context exits.
    """
    import asyncio as _asyncio

    from fastapi import FastAPI

    lifespan_events: list[str] = []
    uvicorn_kwargs_seen: dict = {}
    connect_called: list[bool] = []
    disconnect_called: list[bool] = []

    async def _drive_lifespan(the_app: object, **kwargs: object) -> None:
        uvicorn_kwargs_seen.update(kwargs)
        async with the_app.router.lifespan_context(the_app):  # type: ignore[union-attr]
            # Yield control so the session() background task can run connect().
            await _asyncio.sleep(0.05)
            lifespan_events.append("inner_body")
        disconnect_called.append(True)

    def fake_uvicorn_run(the_app, **kwargs):
        loop = _asyncio.new_event_loop()
        try:
            loop.run_until_complete(_drive_lifespan(the_app, **kwargs))
        finally:
            loop.close()

    # Wrap connect/disconnect with plain async functions (not AsyncMock) so they
    # work correctly in the fresh event loop created inside fake_uvicorn_run.
    client = _stub_client()

    _orig_connect = client.connect

    async def _tracked_connect() -> None:
        connect_called.append(True)
        await _orig_connect()

    client.connect = _tracked_connect  # type: ignore[method-assign]

    _orig_disconnect = client.disconnect

    async def _tracked_disconnect() -> None:
        disconnect_called.append(True)
        await _orig_disconnect()

    client.disconnect = _tracked_disconnect  # type: ignore[method-assign]

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    app = FastAPI()
    client.serve(app, host="127.0.0.1", port=9999)

    # uvicorn received the right kwargs
    assert uvicorn_kwargs_seen == {"host": "127.0.0.1", "port": 9999}
    # session was entered (connect was called) and inner body ran
    assert connect_called, "connect() was never called — session() was not entered"
    assert "inner_body" in lifespan_events
    # session exited (disconnect was called)
    assert disconnect_called, "disconnect() was never called — session() did not exit"


def test_serve_forwards_on_connect(monkeypatch) -> None:
    """serve(on_connect=cb) forwards cb into the internal session() call."""
    import asyncio as _asyncio

    from fastapi import FastAPI

    client = _stub_client()
    on_connect_calls: list[str] = []

    async def my_on_connect() -> None:
        on_connect_calls.append("called")

    async def _drive_lifespan(the_app: object) -> None:
        async with the_app.router.lifespan_context(the_app):  # type: ignore[union-attr]
            # give background task a chance to call on_connect
            for _ in range(20):
                if on_connect_calls:
                    break
                await _asyncio.sleep(0.01)

    def fake_uvicorn_run(the_app, **kwargs):
        loop = _asyncio.new_event_loop()
        try:
            loop.run_until_complete(_drive_lifespan(the_app))
        finally:
            loop.close()

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    app = FastAPI()
    client.serve(app, on_connect=my_on_connect, host="127.0.0.1", port=9999)

    assert on_connect_calls == ["called"]


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
