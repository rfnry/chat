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
async def test_running_calls_on_connect_and_disconnect() -> None:
    client = _stub_client()
    calls: list[str] = []

    async def _on_connect() -> None:
        calls.append("on_connect")

    async with client.running(on_connect=_on_connect):
        # give the background task a chance to reach on_connect
        for _ in range(20):
            if "on_connect" in calls:
                break
            await asyncio.sleep(0.01)
        assert "on_connect" in calls

    # After exit: disconnect was called.
    client._socket.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_running_without_on_connect_still_works() -> None:
    client = _stub_client()
    async with client.running():
        await asyncio.sleep(0.05)
    client._socket.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_running_cancels_run_task_on_exit() -> None:
    client = _stub_client()

    async with client.running():
        pass  # immediate exit — task should be cleaned up

    # The run() task spun up internally must have been cancelled / completed.
    # We don't expose the task, but ensure no asyncio warnings about
    # never-awaited or pending. A sentinel check via gc of tasks is flaky;
    # instead, rely on the contract that running() blocks until cleanup.
    # Assert that after exit, a second running() works cleanly.
    async with client.running():
        pass


@pytest.mark.asyncio
async def test_running_installs_logging_filter() -> None:
    client = _stub_client()
    uvicorn_logger = logging.getLogger("uvicorn.error")

    async with client.running():
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
