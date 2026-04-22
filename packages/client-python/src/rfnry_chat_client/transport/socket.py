from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

AuthenticatePayload = dict[str, Any]
AuthenticateCallable = Callable[[], Awaitable[AuthenticatePayload]]
RawEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class _SioClient(Protocol):
    async def connect(
        self,
        url: str,
        *,
        auth: dict[str, Any] | None = ...,
        headers: dict[str, str] | None = ...,
        transports: list[str] | None = ...,
        socketio_path: str | None = ...,
    ) -> None: ...
    async def disconnect(self) -> None: ...
    def on(self, event: str, handler: Any = ...) -> Any: ...
    async def emit(self, event: str, data: Any = ...) -> None: ...
    async def call(self, event: str, data: Any = ..., *, timeout: float | None = ...) -> Any: ...


class SocketTransportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class SocketTransport:
    def __init__(
        self,
        *,
        base_url: str,
        sio_client: _SioClient | None = None,
        socketio_path: str = "/chat/ws",
        authenticate: AuthenticateCallable | None = None,
    ) -> None:
        if sio_client is None:
            import socketio

            sio_client = socketio.AsyncClient()
        self._sio: _SioClient = sio_client
        self._base_url = base_url.rstrip("/")
        self._socketio_path = socketio_path
        self._authenticate = authenticate

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def socketio_path(self) -> str:
        return self._socketio_path

    async def connect(self) -> None:
        auth_payload: AuthenticatePayload = {}
        if self._authenticate is not None:
            auth_payload = await self._authenticate()
        await self._sio.connect(
            self._base_url,
            auth=auth_payload.get("auth"),
            headers=auth_payload.get("headers"),
            transports=["websocket"],
            socketio_path=self._socketio_path,
        )

    async def disconnect(self) -> None:
        await self._sio.disconnect()

    def on_raw_event(self, name: str, handler: RawEventHandler) -> None:
        self._sio.on(name, handler)

    async def join_thread(
        self,
        thread_id: str,
        since: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"thread_id": thread_id}
        if since is not None:
            payload["since"] = since
        reply = await self._sio.call("thread:join", payload)
        _raise_if_error(reply)
        return reply

    async def leave_thread(self, thread_id: str) -> dict[str, Any]:
        reply = await self._sio.call("thread:leave", {"thread_id": thread_id})
        _raise_if_error(reply)
        return reply

    async def send_message(self, thread_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        reply = await self._sio.call("message:send", {"thread_id": thread_id, "draft": draft})
        _raise_if_error(reply)
        return reply

    async def send_event(self, thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
        reply = await self._sio.call("event:send", {"thread_id": thread_id, "event": event})
        _raise_if_error(reply)
        return reply

    async def begin_run(
        self,
        thread_id: str,
        *,
        triggered_by_event_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"thread_id": thread_id}
        if triggered_by_event_id is not None:
            payload["triggered_by_event_id"] = triggered_by_event_id
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key
        reply = await self._sio.call("run:begin", payload)
        _raise_if_error(reply)
        return reply

    async def end_run(
        self,
        run_id: str,
        *,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"run_id": run_id}
        if error is not None:
            payload["error"] = error
        reply = await self._sio.call("run:end", payload)
        _raise_if_error(reply)
        return reply

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        reply = await self._sio.call("run:cancel", {"run_id": run_id})
        _raise_if_error(reply)
        return reply

    async def send_stream_start(self, frame: dict[str, Any]) -> dict[str, Any]:
        reply = await self._sio.call("stream:start", frame)
        _raise_if_error(reply)
        return reply

    async def send_stream_delta(self, frame: dict[str, Any]) -> None:
        # Fire-and-forget: token streams must not block on per-frame RTT.
        # Awaiting an ack for every delta caps throughput at ~1/RTT tokens/sec
        # (~200 tok/s at 5ms RTT). stream:start and stream:end keep using call
        # because they need ordering/error signaling.
        await self._sio.emit("stream:delta", frame)

    async def send_stream_end(self, frame: dict[str, Any]) -> dict[str, Any]:
        reply = await self._sio.call("stream:end", frame)
        _raise_if_error(reply)
        return reply


def _raise_if_error(reply: Any) -> None:
    if isinstance(reply, dict) and "error" in reply:
        err = reply["error"]
        raise SocketTransportError(err.get("code", "unknown"), err.get("message", ""))
