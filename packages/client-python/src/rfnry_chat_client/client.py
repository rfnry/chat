from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from rfnry_chat_protocol import (
    ContentPart,
    Event,
    Identity,
    ThreadMember,
    parse_event,
)

from rfnry_chat_client.dispatch import Dispatcher, EventHandler
from rfnry_chat_client.transport.rest import RestTransport
from rfnry_chat_client.transport.socket import SocketTransport

AuthenticatePayload = dict[str, Any]
AuthenticateCallable = Callable[[], Awaitable[AuthenticatePayload]]


class ChatClient:
    def __init__(
        self,
        *,
        base_url: str,
        identity: Identity,
        authenticate: AuthenticateCallable | None = None,
        path: str = "/chat",
        socketio_path: str = "/chat/ws",
        http_client: httpx.AsyncClient | None = None,
        socket_transport: SocketTransport | None = None,
    ) -> None:
        self._identity = identity
        self._authenticate = authenticate

        async def _auth_headers() -> dict[str, str]:
            if authenticate is None:
                return {}
            payload = await authenticate()
            return dict(payload.get("headers") or {})

        self._rest = RestTransport(
            base_url=base_url,
            http_client=http_client,
            path=path,
            authenticate=_auth_headers,
        )
        self._socket = socket_transport or SocketTransport(
            base_url=base_url,
            socketio_path=socketio_path,
            authenticate=authenticate,
        )
        self._dispatcher = Dispatcher(identity=identity)

    @property
    def identity(self) -> Identity:
        return self._identity

    @property
    def rest(self) -> RestTransport:
        return self._rest

    @property
    def socket(self) -> SocketTransport:
        return self._socket

    async def connect(self) -> None:
        self._socket.on_raw_event("event", self._dispatcher.feed)
        await self._socket.connect()

    async def disconnect(self) -> None:
        await self._socket.disconnect()
        await self._rest.aclose()

    async def join_thread(
        self, thread_id: str, since: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return await self._socket.join_thread(thread_id, since=since)

    async def leave_thread(self, thread_id: str) -> dict[str, Any]:
        return await self._socket.leave_thread(thread_id)

    async def send_message(
        self,
        thread_id: str,
        *,
        content: list[ContentPart],
        client_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        recipients: list[str] | None = None,
    ) -> Event:
        draft: dict[str, Any] = {
            "client_id": client_id or _gen_client_id(),
            "content": [part.model_dump(mode="json") for part in content],
        }
        if metadata:
            draft["metadata"] = metadata
        if recipients is not None:
            draft["recipients"] = recipients
        reply = await self._socket.send_message(thread_id, draft)
        return parse_event(reply["event"])

    async def add_member(
        self, thread_id: str, identity: Identity, role: str = "member"
    ) -> ThreadMember:
        return await self._rest.add_member(thread_id, identity=identity, role=role)

    async def remove_member(self, thread_id: str, identity_id: str) -> None:
        await self._rest.remove_member(thread_id, identity_id)

    def on_message(
        self,
        handler: EventHandler | None = None,
        *,
        all_events: bool = False,
    ) -> Any:
        return self._register("message", handler, all_events=all_events)

    def on_reasoning(
        self,
        handler: EventHandler | None = None,
        *,
        all_events: bool = False,
    ) -> Any:
        return self._register("reasoning", handler, all_events=all_events)

    def on_tool_result(
        self,
        handler: EventHandler | None = None,
        *,
        all_events: bool = False,
    ) -> Any:
        return self._register("tool.result", handler, all_events=all_events)

    def on_tool_call(
        self,
        arg: EventHandler | str | None = None,
        *,
        all_events: bool = False,
    ) -> Any:
        if callable(arg):
            self._dispatcher.register("tool.call", arg, all_events=False)
            return arg
        tool_name = arg if isinstance(arg, str) else None

        def decorator(handler: EventHandler) -> EventHandler:
            self._dispatcher.register(
                "tool.call", handler, all_events=all_events, tool_name=tool_name
            )
            return handler

        return decorator

    def on_any_event(
        self,
        handler: EventHandler | None = None,
        *,
        all_events: bool = False,
    ) -> Any:
        return self._register("*", handler, all_events=all_events)

    def _register(
        self,
        event_type: str,
        handler: EventHandler | None,
        *,
        all_events: bool,
    ) -> Any:
        if handler is not None:
            self._dispatcher.register(event_type, handler, all_events=all_events)
            return handler

        def decorator(fn: EventHandler) -> EventHandler:
            self._dispatcher.register(event_type, fn, all_events=all_events)
            return fn

        return decorator


def _gen_client_id() -> str:
    return f"c_{secrets.token_hex(8)}"
