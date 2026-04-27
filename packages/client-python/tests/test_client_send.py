from __future__ import annotations

from typing import Any

import pytest
from rfnry_chat_protocol import AssistantIdentity, Event, MessageEvent, TextPart

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.send import Send

ME = AssistantIdentity(id="a_me", name="Me")


class _StubSocket:
    def __init__(self) -> None:
        self.begin_calls: list[dict[str, Any]] = []
        self.end_calls: list[dict[str, Any]] = []
        self._next_run_id = 0

    async def begin_run(
        self,
        thread_id: str,
        *,
        triggered_by_event_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self._next_run_id += 1
        run_id = f"run_{self._next_run_id}"
        self.begin_calls.append(
            {
                "thread_id": thread_id,
                "triggered_by_event_id": triggered_by_event_id,
                "idempotency_key": idempotency_key,
                "run_id": run_id,
            }
        )
        return {"run_id": run_id}

    async def end_run(self, run_id: str, *, error: dict[str, Any] | None = None) -> None:
        self.end_calls.append({"run_id": run_id, "error": error})

    async def send_event(self, thread_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        return {"event": raw}


def _client(socket: _StubSocket) -> ChatClient:
    async def auth() -> dict[str, Any]:
        return {}

    return ChatClient(
        base_url="http://test",
        identity=ME,
        authenticate=auth,
        socket_transport=socket,  # type: ignore[arg-type]
    )


async def test_send_yields_a_send_object_bound_to_thread_and_identity() -> None:
    socket = _StubSocket()
    client = _client(socket)
    async with client.send("t_1") as send:
        assert isinstance(send, Send)
        evt = send.message([TextPart(text="hi")])
        assert evt.thread_id == "t_1"
        assert evt.author.id == "a_me"


async def test_send_opens_run_on_enter_and_closes_cleanly_on_exit() -> None:
    socket = _StubSocket()
    client = _client(socket)
    async with client.send("t_1") as _:
        pass
    assert len(socket.begin_calls) == 1
    assert socket.begin_calls[0]["thread_id"] == "t_1"
    assert len(socket.end_calls) == 1
    assert socket.end_calls[0]["run_id"] == socket.begin_calls[0]["run_id"]
    assert socket.end_calls[0]["error"] is None


async def test_send_propagates_run_id_to_emitted_events() -> None:
    socket = _StubSocket()
    client = _client(socket)
    async with client.send("t_1") as send:
        evt = send.message([TextPart(text="hi")])
    expected_run = socket.begin_calls[0]["run_id"]
    assert evt.run_id == expected_run


async def test_send_emit_publishes_through_client_emit_event() -> None:
    socket = _StubSocket()
    client = _client(socket)
    async with client.send("t_1") as send:
        evt = send.message([TextPart(text="hi")])
        result = await send.emit(evt)
    assert isinstance(result, MessageEvent)
    assert result.thread_id == "t_1"


async def test_send_closes_run_with_error_on_exception() -> None:
    socket = _StubSocket()
    client = _client(socket)
    with pytest.raises(RuntimeError, match="boom"):
        async with client.send("t_1") as _:
            raise RuntimeError("boom")
    assert len(socket.end_calls) == 1
    err = socket.end_calls[0]["error"]
    assert err is not None
    assert err["code"] == "send_error"
    assert "boom" in err["message"]


async def test_send_passes_through_triggered_by_event_id_and_idempotency_key() -> None:
    socket = _StubSocket()
    client = _client(socket)
    async with client.send(
        "t_1",
        triggered_by_event_id="evt_origin",
        idempotency_key="op_1",
    ) as _:
        pass
    call = socket.begin_calls[0]
    assert call["triggered_by_event_id"] == "evt_origin"
    assert call["idempotency_key"] == "op_1"


async def test_send_supports_multiple_emissions_in_one_window() -> None:
    socket = _StubSocket()
    client = _client(socket)
    emitted: list[Event] = []
    async with client.send("t_1") as send:
        emitted.append(await send.emit(send.message([TextPart(text="one")])))
        emitted.append(await send.emit(send.message([TextPart(text="two")])))
    assert len(emitted) == 2
    assert all(e.run_id == socket.begin_calls[0]["run_id"] for e in emitted)
    assert len(socket.end_calls) == 1


async def test_send_lazy_skips_run_open_if_no_emission() -> None:
    socket = _StubSocket()
    client = _client(socket)
    async with client.send("t_1", lazy=True) as _:
        pass
    assert socket.begin_calls == []
    assert socket.end_calls == []


async def test_send_lazy_opens_run_on_first_emit() -> None:
    socket = _StubSocket()
    client = _client(socket)
    async with client.send("t_1", lazy=True) as send:
        assert socket.begin_calls == []
        await send.emit(send.message([TextPart(text="hi")]))
        assert len(socket.begin_calls) == 1
    assert len(socket.end_calls) == 1


async def test_send_triggered_by_event_extracts_event_id() -> None:
    from rfnry_chat_protocol import MessageEvent

    socket = _StubSocket()
    client = _client(socket)
    triggering = MessageEvent(
        id="evt_origin",
        thread_id="t_1",
        author=ME,
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        content=[TextPart(text="trigger")],
    )
    async with client.send("t_1", triggered_by=triggering) as _:
        pass
    assert socket.begin_calls[0]["triggered_by_event_id"] == "evt_origin"


async def test_send_idempotency_key_passes_through() -> None:
    socket = _StubSocket()
    client = _client(socket)
    async with client.send("t_1", idempotency_key="op_abc") as _:
        pass
    assert socket.begin_calls[0]["idempotency_key"] == "op_abc"
