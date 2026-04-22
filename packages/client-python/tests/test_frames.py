from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity, Identity, Run, Thread

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.transport.socket import SocketTransport


async def _noop_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={})


def _build_client() -> tuple[ChatClient, FakeSioClient]:
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_noop_handler)),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
        auto_join_on_invite=False,
    )
    return client, sio


def _thread_payload(thread_id: str = "th_1") -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": thread_id,
        "tenant": {"org": "acme"},
        "metadata": {"topic": "billing"},
        "created_at": now,
        "updated_at": now,
    }


def _run_payload(run_id: str = "run_1", status: str = "running") -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    actor = {"role": "assistant", "id": "a_me", "name": "Me", "metadata": {}}
    trig = {"role": "user", "id": "u_alice", "name": "Alice", "metadata": {}}
    return {
        "id": run_id,
        "thread_id": "th_1",
        "actor": actor,
        "triggered_by": trig,
        "status": status,
        "started_at": now,
        "completed_at": None,
        "error": None,
        "idempotency_key": None,
        "metadata": {},
    }


async def test_on_thread_updated_fires_on_frame() -> None:
    client, sio = _build_client()
    received: list[Thread] = []

    @client.on_thread_updated()
    async def handle(thread: Thread) -> None:
        received.append(thread)

    await client.connect()
    raw = sio.handlers["thread:updated"]
    await raw(_thread_payload())

    assert len(received) == 1
    assert received[0].id == "th_1"
    assert received[0].tenant == {"org": "acme"}
    assert received[0].metadata == {"topic": "billing"}


async def test_on_members_updated_fires_on_frame() -> None:
    client, sio = _build_client()
    received: list[tuple[str, list[Identity]]] = []

    @client.on_members_updated()
    def handle(thread_id: str, members: list[Identity]) -> None:
        # Sync handler — FrameDispatcher should still dispatch it correctly.
        received.append((thread_id, members))

    await client.connect()
    raw = sio.handlers["members:updated"]
    await raw(
        {
            "thread_id": "th_1",
            "members": [
                {"role": "assistant", "id": "a_me", "name": "Me", "metadata": {}},
                {"role": "user", "id": "u_alice", "name": "Alice", "metadata": {}},
            ],
        }
    )

    assert len(received) == 1
    thread_id, members = received[0]
    assert thread_id == "th_1"
    assert len(members) == 2
    assert members[0].id == "a_me"
    assert members[0].role == "assistant"
    assert members[1].id == "u_alice"
    assert members[1].role == "user"


async def test_on_run_updated_fires_on_frame() -> None:
    client, sio = _build_client()
    received: list[Run] = []

    @client.on_run_updated()
    async def handle(run: Run) -> None:
        received.append(run)

    await client.connect()
    raw = sio.handlers["run:updated"]
    await raw(_run_payload(status="completed"))

    assert len(received) == 1
    assert received[0].id == "run_1"
    assert received[0].thread_id == "th_1"
    assert received[0].status == "completed"
