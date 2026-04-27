from __future__ import annotations

from typing import Any

from rfnry_chat_protocol import (
    AssistantIdentity,
    Identity,
    MessageEvent,
    TextPart,
    Thread,
    ThreadMember,
    UserIdentity,
)

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.send import Send

ME = AssistantIdentity(id="a_me", name="Me")
ALICE = UserIdentity(id="u_alice", name="Alice")


class _StubSocket:
    def __init__(self) -> None:
        self.begin_calls: list[dict[str, Any]] = []
        self.end_calls: list[dict[str, Any]] = []
        self.join_calls: list[str] = []
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
            {"thread_id": thread_id, "triggered_by_event_id": triggered_by_event_id, "run_id": run_id}
        )
        return {"run_id": run_id}

    async def end_run(self, run_id: str, *, error: dict[str, Any] | None = None) -> None:
        self.end_calls.append({"run_id": run_id, "error": error})

    async def send_event(self, thread_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        return {"event": raw}

    async def join_thread(self, thread_id: str, since: dict[str, str] | None = None) -> dict[str, Any]:
        self.join_calls.append(thread_id)
        return {"thread_id": thread_id, "replayed": [], "replay_truncated": False}


class _StubRest:
    def __init__(self) -> None:
        self.create_thread_calls: list[dict[str, Any]] = []
        self.add_member_calls: list[tuple[str, str]] = []
        self._counter = 0
        self._created_by_client_id: dict[str, Thread] = {}

    async def create_thread(
        self,
        *,
        tenant: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        client_id: str | None = None,
    ) -> Thread:
        self.create_thread_calls.append({"tenant": tenant, "metadata": metadata, "client_id": client_id})
        if client_id is not None and client_id in self._created_by_client_id:
            return self._created_by_client_id[client_id]
        self._counter += 1
        from datetime import UTC, datetime

        t = Thread(
            id=f"th_{self._counter}",
            tenant=tenant or {},
            metadata=metadata or {},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        if client_id is not None:
            self._created_by_client_id[client_id] = t
        return t

    async def add_member(self, thread_id: str, *, identity: Identity, role: str = "member") -> ThreadMember:
        self.add_member_calls.append((thread_id, identity.id))
        from datetime import UTC, datetime

        return ThreadMember(
            thread_id=thread_id,
            identity_id=identity.id,
            identity=identity,
            added_at=datetime.now(UTC),
            added_by=identity,
            role=role,
        )


def _client(socket: _StubSocket, rest: _StubRest) -> ChatClient:
    async def auth() -> dict[str, Any]:
        return {}

    c = ChatClient(
        base_url="http://test",
        identity=ME,
        authenticate=auth,
        socket_transport=socket,  # type: ignore[arg-type]
    )
    c._rest = rest  # type: ignore[assignment]  # test-only: swap in stubbed REST
    return c


async def test_send_to_yields_send_bound_to_new_thread() -> None:
    socket = _StubSocket()
    rest = _StubRest()
    client = _client(socket, rest)
    async with client.send_to(ALICE) as send:
        assert isinstance(send, Send)
        assert send.thread_id.startswith("th_")
        assert send.run_id is not None
    assert len(rest.create_thread_calls) == 1
    assert len(rest.add_member_calls) == 1
    assert rest.add_member_calls[0][1] == "u_alice"


async def test_send_to_joins_the_thread() -> None:
    socket = _StubSocket()
    rest = _StubRest()
    client = _client(socket, rest)
    async with client.send_to(ALICE) as send:
        assert send.thread_id in socket.join_calls


async def test_send_to_reuses_thread_on_same_client_id() -> None:
    socket = _StubSocket()
    rest = _StubRest()
    client = _client(socket, rest)
    async with client.send_to(ALICE, client_id="op_alpha") as a:
        first_thread = a.thread_id
    async with client.send_to(ALICE, client_id="op_alpha") as b:
        assert b.thread_id == first_thread


async def test_send_to_passes_tenant_and_metadata_through() -> None:
    socket = _StubSocket()
    rest = _StubRest()
    client = _client(socket, rest)
    async with client.send_to(ALICE, tenant={"org": "X"}, metadata={"kind": "dm"}) as _:
        pass
    call = rest.create_thread_calls[0]
    assert call["tenant"] == {"org": "X"}
    assert call["metadata"] == {"kind": "dm"}


async def test_send_to_supports_emission() -> None:
    socket = _StubSocket()
    rest = _StubRest()
    client = _client(socket, rest)
    async with client.send_to(ALICE) as send:
        evt = await send.emit(send.message([TextPart(text="Hi")]))
    assert isinstance(evt, MessageEvent)
    assert evt.thread_id == send.thread_id


async def test_send_to_lazy_skips_run_open_if_no_emit() -> None:
    socket = _StubSocket()
    rest = _StubRest()
    client = _client(socket, rest)
    async with client.send_to(ALICE, lazy=True) as _:
        pass
    assert socket.begin_calls == []
    assert socket.end_calls == []


async def test_send_to_idempotency_key_passes_to_run() -> None:
    socket = _StubSocket()
    rest = _StubRest()
    client = _client(socket, rest)
    async with client.send_to(ALICE, idempotency_key="op_run") as send:
        await send.emit(send.message([TextPart(text="hi")]))
    # Wire payload retains it (StubSocket.begin_calls captures triggered_by but
    # not idempotency_key explicitly — tested separately in test_client_send.py;
    # here we verify no error and one run was opened).
    assert len(socket.begin_calls) == 1


async def test_send_to_triggered_by_event_extracts_event_id() -> None:
    from datetime import UTC, datetime

    socket = _StubSocket()
    rest = _StubRest()
    client = _client(socket, rest)
    triggering = MessageEvent(
        id="evt_origin",
        thread_id="other_thread",
        author=ALICE,
        created_at=datetime.now(UTC),
        content=[TextPart(text="trigger")],
    )
    async with client.send_to(ALICE, triggered_by=triggering) as _:
        pass
    assert socket.begin_calls[0]["triggered_by_event_id"] == "evt_origin"
