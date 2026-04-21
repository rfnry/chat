from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from rfnry_chat_protocol import (
    ContentPart,
    Event,
    Identity,
    Run,
    RunError,
    ThreadMember,
    parse_event,
)

from rfnry_chat_client.dispatch import Dispatcher
from rfnry_chat_client.handler.types import HandlerCallable
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
        self._dispatcher = Dispatcher(identity=identity, client=self)

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

    async def emit_event(self, event: Event) -> Event:
        reply = await self._socket.send_event(
            event.thread_id,
            event.model_dump(mode="json", by_alias=True),
        )
        return parse_event(reply["event"])

    async def begin_run(
        self,
        thread_id: str,
        *,
        triggered_by_event_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Run:
        reply = await self._socket.begin_run(
            thread_id,
            triggered_by_event_id=triggered_by_event_id,
            idempotency_key=idempotency_key,
        )
        return await self._rest.get_run(reply["run_id"])

    async def end_run(
        self,
        run_id: str,
        *,
        error: RunError | None = None,
    ) -> Run:
        payload: dict[str, Any] | None = None
        if error is not None:
            payload = {"code": error.code, "message": error.message}
        reply = await self._socket.end_run(run_id, error=payload)
        return await self._rest.get_run(reply["run_id"])

    async def add_member(
        self, thread_id: str, identity: Identity, role: str = "member"
    ) -> ThreadMember:
        return await self._rest.add_member(thread_id, identity=identity, role=role)

    async def remove_member(self, thread_id: str, identity_id: str) -> None:
        await self._rest.remove_member(thread_id, identity_id)

    def on(
        self,
        event_type: str,
        *,
        tool: str | None = None,
        all_events: bool = False,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        def decorator(handler: HandlerCallable) -> HandlerCallable:
            self._dispatcher.register(
                event_type,
                handler,
                all_events=all_events,
                tool_name=tool,
            )
            return handler

        return decorator

    def on_message(
        self, *, all_events: bool = False
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("message", all_events=all_events)

    def on_reasoning(
        self, *, all_events: bool = False
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("reasoning", all_events=all_events)

    def on_tool_call(
        self,
        name: str | None = None,
        *,
        all_events: bool = False,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("tool.call", tool=name, all_events=all_events)

    def on_tool_result(
        self, *, all_events: bool = False
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("tool.result", all_events=all_events)

    def on_any_event(
        self, *, all_events: bool = False
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("*", all_events=all_events)


def _gen_client_id() -> str:
    return f"c_{secrets.token_hex(8)}"
