from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypedDict

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

from rfnry_chat_client.frames import (
    FrameDispatcher,
    MembersUpdatedHandler,
    PresenceJoinedHandler,
    PresenceLeftHandler,
    RunUpdatedHandler,
    ThreadUpdatedHandler,
)
from rfnry_chat_client.handler.dispatcher import HandlerDispatcher
from rfnry_chat_client.handler.types import HandlerCallable
from rfnry_chat_client.inbox import InboxDispatcher, InviteHandler
from rfnry_chat_client.members_cache import MembersCache
from rfnry_chat_client.send import Send
from rfnry_chat_client.transport.rest import RestTransport
from rfnry_chat_client.transport.socket import SocketTransport


class JoinThreadResult(TypedDict):
    thread_id: str
    replayed: list[Event]
    replay_truncated: bool

AuthenticatePayload = dict[str, Any]
AuthenticateCallable = Callable[[], Awaitable[AuthenticatePayload]]

_log = logging.getLogger("rfnry_chat_client.runner")


class _LifespanNoiseFilter(logging.Filter):
    _CANCELLED_MARKERS = ("asyncio.CancelledError", "asyncio.exceptions.CancelledError")

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.msg, str):
            return True

        if record.msg.startswith("Exception in 'lifespan' protocol"):
            exc_type = record.exc_info[0] if record.exc_info else None
            if exc_type is None:
                return True
            try:
                is_cancelled = issubclass(exc_type, asyncio.CancelledError)
            except TypeError:
                is_cancelled = False
            return not is_cancelled

        if record.msg.startswith("Traceback (most recent call last):") and any(
            marker in record.msg for marker in self._CANCELLED_MARKERS
        ):
            return False
        return True


_LIFESPAN_NOISE_FILTER_INSTALLED = False


def _install_lifespan_noise_filter() -> None:
    global _LIFESPAN_NOISE_FILTER_INSTALLED
    if _LIFESPAN_NOISE_FILTER_INSTALLED:
        return
    logging.getLogger("uvicorn.error").addFilter(_LifespanNoiseFilter())
    _LIFESPAN_NOISE_FILTER_INSTALLED = True


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
        socket_call_timeout: float = 15.0,
        member_cache_ttl_seconds: float = 5.0,
    ) -> None:
        self._identity = identity
        self._member_cache_ttl_seconds = member_cache_ttl_seconds

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
        self._socket_call_timeout = socket_call_timeout
        self._socket = socket_transport or SocketTransport(
            base_url=base_url,
            socketio_path=socketio_path,
            authenticate=authenticate,
            socket_call_timeout=socket_call_timeout,
        )
        self._dispatcher = HandlerDispatcher(identity=identity, client=self)
        self._inbox = InboxDispatcher(client=self, auto_join=auto_join_on_invite)
        self._frames = FrameDispatcher()
        self._members_cache = MembersCache(self._rest, ttl_seconds=member_cache_ttl_seconds)

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
        self._socket.on_raw_event("members:updated", self._on_members_updated_frame)
        self._socket.on_raw_event("run:updated", self._frames.feed_run_updated)
        self._socket.on_raw_event("presence:joined", self._frames.feed_presence_joined)
        self._socket.on_raw_event("presence:left", self._frames.feed_presence_left)
        await self._socket.connect()

    async def _on_members_updated_frame(self, raw: dict[str, Any]) -> None:
        thread_id = raw.get("thread_id")
        if isinstance(thread_id, str):
            self._members_cache.invalidate(thread_id)
        await self._frames.feed_members_updated(raw)

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
            socket_call_timeout=self._socket_call_timeout,
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

    @asynccontextmanager
    async def running(
        self,
        *,
        on_connect: Callable[[], Awaitable[None]] | None = None,
        connect_retries: int = 50,
        connect_backoff_seconds: float = 0.2,
        max_backoff_seconds: float = 30.0,
        disconnect_timeout: float = 5.0,
    ) -> AsyncIterator[None]:

        _install_lifespan_noise_filter()
        task = asyncio.create_task(
            self.run(
                on_connect=on_connect,
                connect_retries=connect_retries,
                connect_backoff_seconds=connect_backoff_seconds,
                max_backoff_seconds=max_backoff_seconds,
            )
        )
        try:
            yield
        finally:
            with contextlib.suppress(BaseException):
                await self.disconnect()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(task, timeout=disconnect_timeout)

    async def join_thread(self, thread_id: str, since: dict[str, str] | None = None) -> JoinThreadResult:
        reply = await self._socket.join_thread(thread_id, since=since)
        return JoinThreadResult(
            thread_id=reply.get("thread_id", thread_id),
            replayed=[parse_event(e) for e in reply.get("replayed", [])],
            replay_truncated=bool(reply.get("replay_truncated", False)),
        )

    async def leave_thread(self, thread_id: str) -> dict[str, Any]:
        return await self._socket.leave_thread(thread_id)

    async def backfill(
        self,
        thread_id: str,
        *,
        before: tuple[str, str],
        limit: int = 100,
    ) -> tuple[list[Event], bool]:
        page = await self._rest.list_events(thread_id, limit=limit, before=before)
        items: list[Event] = page["items"]
        return items, len(items) >= limit

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
        result = parse_event(reply["event"])
        await self._dispatcher.feed_event(result)
        return result

    async def emit_event(self, event: Event) -> Event:
        reply = await self._socket.send_event(
            event.thread_id,
            event.model_dump(mode="json", by_alias=True),
        )
        result = parse_event(reply["event"])
        await self._dispatcher.feed_event(result)
        return result

    async def begin_run(
        self,
        thread_id: str,
        *,
        triggered_by_event_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:

        reply = await self._socket.begin_run(
            thread_id,
            triggered_by_event_id=triggered_by_event_id,
            idempotency_key=idempotency_key,
        )
        return reply["run_id"]

    async def end_run(
        self,
        run_id: str,
        *,
        error: RunError | None = None,
    ) -> None:

        payload: dict[str, Any] | None = None
        if error is not None:
            payload = {"code": error.code, "message": error.message}
        await self._socket.end_run(run_id, error=payload)

    async def get_run(self, run_id: str) -> Run:

        return await self._rest.get_run(run_id)

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        return await self._socket.cancel_run(run_id)

    @asynccontextmanager
    async def send_to(
        self,
        identity: Identity,
        *,
        thread_id: str | None = None,
        tenant: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        client_id: str | None = None,
        triggered_by: Event | Identity | None = None,
        idempotency_key: str | None = None,
        lazy: bool = False,
    ) -> AsyncIterator[Send]:
        if thread_id is not None:
            thread = await self._rest.get_thread(thread_id)
        else:
            thread = await self._rest.create_thread(
                tenant=tenant,
                metadata=metadata,
                client_id=client_id or _gen_client_id(),
            )
        await self.add_member(thread.id, identity)
        await self.join_thread(thread.id)
        async with self.send(
            thread.id,
            triggered_by=triggered_by,
            idempotency_key=idempotency_key,
            lazy=lazy,
        ) as send:
            yield send

    @asynccontextmanager
    async def send(
        self,
        thread_id: str,
        *,
        triggered_by: Event | Identity | None = None,
        triggered_by_event_id: str | None = None,
        idempotency_key: str | None = None,
        lazy: bool = False,
    ) -> AsyncIterator[Send]:
        resolved_event_id = triggered_by_event_id
        if triggered_by is not None and resolved_event_id is None:
            if isinstance(triggered_by, Event):
                resolved_event_id = triggered_by.id

        opened_run_id: list[str] = []

        async def _start_run() -> str:
            if opened_run_id:
                return opened_run_id[0]
            run_id = await self.begin_run(
                thread_id,
                triggered_by_event_id=resolved_event_id,
                idempotency_key=idempotency_key,
            )
            opened_run_id.append(run_id)
            return run_id

        if not lazy:
            await _start_run()

        send = Send(
            thread_id=thread_id,
            author=self._identity,
            run_id=opened_run_id[0] if opened_run_id else None,
            client=self,
            run_starter=_start_run,
        )
        try:
            yield send
        except BaseException as exc:
            if opened_run_id:
                await self.end_run(opened_run_id[0], error=RunError(code="send_error", message=str(exc)))
            raise
        if opened_run_id:
            await self.end_run(opened_run_id[0])

    async def add_member(self, thread_id: str, identity: Identity, role: str = "member") -> ThreadMember:
        member = await self._rest.add_member(thread_id, identity=identity, role=role)
        self._members_cache.invalidate(thread_id)
        return member

    async def remove_member(self, thread_id: str, identity_id: str) -> None:
        await self._rest.remove_member(thread_id, identity_id)
        self._members_cache.invalidate(thread_id)

    async def list_members(self, thread_id: str) -> list[ThreadMember]:
        return await self._members_cache.get(thread_id)

    def invalidate_members_cache(self, thread_id: str) -> None:
        self._members_cache.invalidate(thread_id)

    def on(
        self,
        event_type: str,
        *,
        tool: str | None = None,
        all_events: bool = False,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        def decorator(handler: HandlerCallable) -> HandlerCallable:
            self._dispatcher.register(
                event_type,
                handler,
                all_events=all_events,
                tool_name=tool,
                lazy_run=lazy_run,
                idempotency_key=idempotency_key,
            )
            return handler

        return decorator

    def on_message(
        self,
        *,
        all_events: bool = False,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("message", all_events=all_events, lazy_run=lazy_run, idempotency_key=idempotency_key)

    def on_reasoning(
        self,
        *,
        all_events: bool = False,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("reasoning", all_events=all_events, lazy_run=lazy_run, idempotency_key=idempotency_key)

    def on_tool_call(
        self,
        name: str | None = None,
        *,
        all_events: bool = False,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on(
            "tool.call",
            tool=name,
            all_events=all_events,
            lazy_run=lazy_run,
            idempotency_key=idempotency_key,
        )

    def on_tool_result(
        self,
        *,
        all_events: bool = False,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("tool.result", all_events=all_events, lazy_run=lazy_run, idempotency_key=idempotency_key)

    def on_any_event(
        self,
        *,
        all_events: bool = False,
        lazy_run: bool = False,
        idempotency_key: Callable[[Event], str | None] | None = None,
    ) -> Callable[[HandlerCallable], HandlerCallable]:
        return self.on("*", all_events=all_events, lazy_run=lazy_run, idempotency_key=idempotency_key)

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

    def on_presence_joined(
        self,
    ) -> Callable[[PresenceJoinedHandler], PresenceJoinedHandler]:
        def decorator(handler: PresenceJoinedHandler) -> PresenceJoinedHandler:
            return self._frames.register_presence_joined(handler)

        return decorator

    def on_presence_left(
        self,
    ) -> Callable[[PresenceLeftHandler], PresenceLeftHandler]:
        def decorator(handler: PresenceLeftHandler) -> PresenceLeftHandler:
            return self._frames.register_presence_left(handler)

        return decorator


def _gen_client_id() -> str:
    return f"c_{secrets.token_hex(8)}"
