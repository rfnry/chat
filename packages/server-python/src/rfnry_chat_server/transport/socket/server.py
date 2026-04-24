from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import socketio

from rfnry_chat_server.transport.socket.namespace import DEFAULT_REPLAY_CAP, ThreadNamespace

if TYPE_CHECKING:
    from rfnry_chat_server.server import ChatServer


class SocketTransport:
    def __init__(
        self,
        server: ChatServer,
        replay_cap: int = DEFAULT_REPLAY_CAP,
        *,
        cors_allowed_origins: str | list[str] = "*",
        ping_interval: float = 20,
        ping_timeout: float = 20,
    ) -> None:
        self._server = server
        self._replay_cap = replay_cap
        # When namespace_keys is set, register under the wildcard "*" so
        # python-socketio routes every dynamic `/A`, `/A/ws_X`, etc. to this
        # namespace. Otherwise stay on the default `/` path.
        wildcard = server.namespace_keys is not None
        self._sio = socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins=cors_allowed_origins,
            # `namespaces="*"` tells python-socketio's _handle_connect to
            # accept any dynamic namespace path; without it, only paths
            # explicitly listed (default `["/"]`) are allowed.
            namespaces="*" if wildcard else None,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
        )
        self._socketio_path = "/chat/ws"
        ns_path = "*" if wildcard else "/"
        self._namespace = ThreadNamespace(ns_path, server=server, replay_cap=replay_cap)
        self._sio.register_namespace(self._namespace)

    @property
    def sio(self) -> socketio.AsyncServer:
        return self._sio

    def asgi_app(self, other_asgi_app: Any = None) -> Any:
        inner = socketio.ASGIApp(self._sio, other_asgi_app, socketio_path=self._socketio_path)
        return _suppress_ws_shutdown_cancel(inner)


def _suppress_ws_shutdown_cancel(inner: Any) -> Any:
    async def app(scope: dict[str, Any], receive: Any, send: Any) -> Any:
        try:
            return await inner(scope, receive, send)
        except asyncio.CancelledError:
            if scope.get("type") == "websocket":
                return None
            raise

    return app
