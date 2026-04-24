from __future__ import annotations

from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.transport.socket.server import SocketTransport


class _StubStore:
    async def ensure_schema(self) -> None:
        return None


def _server() -> ChatServer:
    return ChatServer(store=_StubStore())  # type: ignore[arg-type]


def test_cors_allowed_origins_default_is_wildcard() -> None:
    sio = SocketTransport(_server())
    assert sio.sio.eio.cors_allowed_origins == "*"


def test_cors_allowed_origins_accepts_allowlist() -> None:
    sio = SocketTransport(_server(), cors_allowed_origins=["https://app.example.com"])
    assert sio.sio.eio.cors_allowed_origins == ["https://app.example.com"]


def test_ping_defaults_are_tighter_than_python_socketio_defaults() -> None:
    sio = SocketTransport(_server())
    assert sio.sio.eio.ping_interval == 20
    assert sio.sio.eio.ping_timeout == 20


def test_ping_interval_and_timeout_are_configurable() -> None:
    sio = SocketTransport(_server(), ping_interval=10, ping_timeout=15)
    assert sio.sio.eio.ping_interval == 10
    assert sio.sio.eio.ping_timeout == 15
