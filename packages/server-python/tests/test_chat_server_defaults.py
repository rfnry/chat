from __future__ import annotations

import logging

import pytest

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer


class _StubStore:
    async def ensure_schema(self) -> None:
        return None


@pytest.mark.asyncio
async def test_default_authenticate_logs_warning_on_start(caplog) -> None:
    server = ChatServer(store=_StubStore())  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING, logger="rfnry_chat_server.server"):
        await server.start()
        await server.stop()
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("authenticate" in m.lower() for m in warnings)


@pytest.mark.asyncio
async def test_explicit_authenticate_does_not_warn(caplog) -> None:
    async def auth(_h: HandshakeData):
        return None

    server = ChatServer(store=_StubStore(), authenticate=auth)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING, logger="rfnry_chat_server.server"):
        await server.start()
        await server.stop()
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("authenticate" in m.lower() for m in warnings)
