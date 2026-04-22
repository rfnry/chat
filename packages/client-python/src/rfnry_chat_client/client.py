from __future__ import annotations

import asyncio
import contextlib
import logging
import random
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
    Thread,
    ThreadMember,
    parse_event,
)

from rfnry_chat_client.dispatch import Dispatcher
from rfnry_chat_client.frames import (
    FrameDispatcher,
    MembersUpdatedHandler,
    RunUpdatedHandler,
    ThreadUpdatedHandler,
)
from rfnry_chat_client.handler.types import HandlerCallable
from rfnry_chat_client.inbox import InboxDispatcher, InviteHandler
from rfnry_chat_client.transport.rest import RestTransport
from rfnry_chat_client.transport.socket import SocketTransport

AuthenticatePayload = dict[str, Any]
AuthenticateCallable = Callable[[], Awaitable[AuthenticatePayload]]

_log = logging.getLogger("rfnry_chat_client.runner")


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
        auto_join_on_invite: bool = True,
    ) -> None:
        self._identity = identity

        if authenticate is None:
            import base64
            import json as _json

            raw = identity.model_dump(mode="json")
            encoded = base64.urlsafe_b64encode(_json.dumps(raw, separators=(",", ":")).encode("utf-8")).decode("ascii")
            identity_payload = {
                "auth": {"identity": raw},
                "headers": {"x-rfnry-identity": encoded},
            }

            async def _default_auth() -> AuthenticatePayload:
                return identity_payload

            authenticate = _default_auth

        self._authenticate = authenticate

        async def _auth_headers() -> dict[str, str]:
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
        self._inbox = InboxDispatcher(client=self, auto_join=auto_join_on_invite)
        self._frames = FrameDispatcher()

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
        self._socket.on_raw_event("thread:invited", self._inbox.feed)
        self._socket.on_raw_event("thread:updated", self._frames.feed_thread_updated)
        self._socket.on_raw_event("members:updated", self._frames.feed_members_updated)
        self._socket.on_raw_event("run:updated", self._frames.feed_run_updated)
        await self._socket.connect()

    async def disconnect(self) -> None:
        await self._socket.disconnect()
        await self._rest.aclose()

    async def reconnect(
        self,
        *,
        base_url: str | None = None,
        authenticate: AuthenticateCallable | None = None,
        http_client: httpx.AsyncClient | None = None,
        socket_transport: SocketTransport | None = None,
        path: str | None = None,
        socketio_path: str | None = None,
    ) -> None:
        """Disconnect, rebuild transports with new options, reconnect.

        Handler registrations survive — they live on the dispatcher, which is
        not replaced.
        """
        try:
            await self._socket.disconnect()
        except Exception:
            pass
        try:
            await self._rest.aclose()
        except Exception:
            pass

        if authenticate is not None:
            self._authenticate = authenticate

        new_base = base_url if base_url is not None else self._rest.base_url
        new_path = path if path is not None else self._rest.path
        new_sio_path = socketio_path if socketio_path is not None else self._socket.socketio_path

        async def _auth_headers() -> dict[str, str]:
            if self._authenticate is None:
                return {}
            payload = await self._authenticate()
            return dict(payload.get("headers") or {})

        self._rest = RestTransport(
            base_url=new_base,
            http_client=http_client,
            path=new_path,
            authenticate=_auth_headers,
        )
        self._socket = socket_transport or SocketTransport(
            base_url=new_base,
            socketio_path=new_sio_path,
            authenticate=self._authenticate,
        )
        await self.connect()

    async def run(
        self,
        *,
        connect_retries: int = 50,
        connect_backoff_seconds: float = 0.2,
        max_backoff_seconds: float = 30.0,
        on_connect: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        last_error: BaseException | None = None
        for attempt in range(1, connect_retries + 1):
            try:
                await self.connect()
                _log.info("connected on attempt=%d", attempt)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                _log.debug("connect retry=%d: %s", attempt, exc)
                if attempt < connect_retries:
                    base = min(
                        connect_backoff_seconds * (2 ** (attempt - 1)),
                        max_backoff_seconds,
                    )
                    # Floored jitter in [0.5 * base, 1.5 * base) — exponential growth with
                    # a 1x-wide spread that breaks lockstep across a fleet of clients.
                    delay = base * (0.5 + random.random())
                    await asyncio.sleep(delay)
        if last_error is not None:
            raise ConnectionError(f"failed to connect after {connect_retries} attempts") from last_error

        try:
            if on_connect is not None:
                await on_connect()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if (task := asyncio.current_task()) is not None:
                task.uncancel()
        finally:
            with contextlib.suppress(BaseException):
                await self.disconnect()
            _log.info("disconnected")

    async def join_thread(self, thread_id: str, since: dict[str, str] | None = None) -> dict[str, Any]:
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

    async def add_member(self, thread_id: str, identity: Identity, role: str = "member") -> ThreadMember:
        return await self._rest.add_member(thread_id, identity=identity, role=role)

    async def remove_member(self, thread_id: str, identity_id: str) -> None:
        await self._rest.remove_member(thread_id, identity_id)

    async def open_thread_with(
        self,
        *,
        message: list[ContentPart],
        invite: Identity | None = None,
        thread_id: str | None = None,
        tenant: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        client_id: str | None = None,
    ) -> tuple[Thread, Event]:
        """Proactively open (or reuse) a thread, optionally invite a participant, and send a message.

        - If ``thread_id`` is None, creates a new thread (this client becomes first member).
          Thread creation is idempotent per ``client_id``; one is auto-generated if not supplied
          so retries of the whole call return the same thread rather than stacking duplicates.
        - If ``invite`` is provided, adds them (add_member is idempotent server-side,
          so no preflight is performed).
        - Joins the thread room (idempotent).
        - Sends the message, recipients defaulting to ``[invite.id]`` if invite was specified.

        Returns ``(thread, sent_event)``.
        """
        if thread_id is None:
            import uuid

            thread = await self._rest.create_thread(
                tenant=tenant,
                metadata=metadata,
                client_id=client_id or str(uuid.uuid4()),
            )
        else:
            thread = await self._rest.get_thread(thread_id)

        if invite is not None:
            # add_member is idempotent server-side (ON CONFLICT DO NOTHING);
            # no pre-flight needed.
            await self.add_member(thread.id, invite)

        await self.join_thread(thread.id)

        recipients = [invite.id] if invite is not None else None
        event = await self.send_message(thread.id, content=message, recipients=recipients)
        return thread, event

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

    def on_message(self, *, all_events: bool = False) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("message", all_events=all_events)

    def on_reasoning(self, *, all_events: bool = False) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("reasoning", all_events=all_events)

    def on_tool_call(
        self,
        name: str | None = None,
        *,
        all_events: bool = False,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("tool.call", tool=name, all_events=all_events)

    def on_tool_result(self, *, all_events: bool = False) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("tool.result", all_events=all_events)

    def on_any_event(self, *, all_events: bool = False) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("*", all_events=all_events)

    def on_invited(self) -> Callable[[InviteHandler], InviteHandler]:
        def decorator(handler: InviteHandler) -> InviteHandler:
            return self._inbox.register(handler)

        return decorator

    def on_thread_updated(
        self,
    ) -> Callable[[ThreadUpdatedHandler], ThreadUpdatedHandler]:
        def decorator(handler: ThreadUpdatedHandler) -> ThreadUpdatedHandler:
            return self._frames.register_thread_updated(handler)

        return decorator

    def on_members_updated(
        self,
    ) -> Callable[[MembersUpdatedHandler], MembersUpdatedHandler]:
        def decorator(handler: MembersUpdatedHandler) -> MembersUpdatedHandler:
            return self._frames.register_members_updated(handler)

        return decorator

    def on_run_updated(
        self,
    ) -> Callable[[RunUpdatedHandler], RunUpdatedHandler]:
        def decorator(handler: RunUpdatedHandler) -> RunUpdatedHandler:
            return self._frames.register_run_updated(handler)

        return decorator


def _gen_client_id() -> str:
    return f"c_{secrets.token_hex(8)}"
