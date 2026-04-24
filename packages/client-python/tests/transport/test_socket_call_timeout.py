from __future__ import annotations

from typing import Any

import pytest

from rfnry_chat_client.transport.socket import SocketTransport


class _FakeSio:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, dict[str, Any]]] = []

    async def connect(self, *args, **kwargs) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    def on(self, event: str, handler: Any = None) -> Any:
        return None

    async def emit(self, event: str, data: Any = None) -> None:
        return None

    async def call(self, event: str, data: Any = None, *, timeout: float | None = None) -> Any:
        self.calls.append((event, data, {"timeout": timeout}))
        return {"ok": True}


@pytest.mark.asyncio
async def test_every_call_passes_explicit_timeout() -> None:
    sio = _FakeSio()
    transport = SocketTransport(base_url="http://test", sio_client=sio, socket_call_timeout=12.0)

    await transport.join_thread("th_x")
    await transport.leave_thread("th_x")
    await transport.send_message("th_x", {})
    await transport.send_event("th_x", {})
    await transport.begin_run("th_x")
    await transport.end_run("run_y")
    await transport.cancel_run("run_y")
    await transport.send_stream_start({})
    await transport.send_stream_end({})

    # 9 calls, each with timeout=12.0
    assert len(sio.calls) == 9
    assert all(c[2]["timeout"] == 12.0 for c in sio.calls), sio.calls


@pytest.mark.asyncio
async def test_default_call_timeout_is_15_seconds() -> None:
    sio = _FakeSio()
    transport = SocketTransport(base_url="http://test", sio_client=sio)
    await transport.join_thread("th_x")
    assert sio.calls[0][2]["timeout"] == 15.0


@pytest.mark.asyncio
async def test_stream_delta_is_not_timed_out() -> None:
    """stream:delta is emit-only — no timeout semantics apply."""
    sio = _FakeSio()
    transport = SocketTransport(base_url="http://test", sio_client=sio)
    await transport.send_stream_delta({})
    # emit was called (no entry in sio.calls), and no exception raised.
    assert sio.calls == []
