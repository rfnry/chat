from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import Identity, Thread, UserIdentity

from rfnry_chat_server import RecordingBroadcaster
from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def setup(clean_db: asyncpg.Pool) -> tuple[AsyncClient, str]:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    return client, create.json()["id"]


@pytest.fixture
async def setup_with_broadcaster(
    clean_db: asyncpg.Pool,
) -> tuple[AsyncClient, str, RecordingBroadcaster]:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    recorder = RecordingBroadcaster()
    chat_server = ChatServer(store=store, authenticate=auth, broadcaster=recorder)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    return client, create.json()["id"], recorder


async def test_list_members_includes_creator(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    resp = await client.get(f"/chat/threads/{thread_id}/members")
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["identity_id"] == "u_alice"


async def test_add_member(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    resp = await client.post(
        f"/chat/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "user",
                "id": "u_bob",
                "name": "Bob",
                "metadata": {},
            }
        },
    )
    assert resp.status_code == 201

    list_resp = await client.get(f"/chat/threads/{thread_id}/members")
    ids = {m["identity_id"] for m in list_resp.json()}
    assert ids == {"u_alice", "u_bob"}


async def test_add_member_broadcasts_thread_invited_to_new_member(
    setup_with_broadcaster: tuple[AsyncClient, str, RecordingBroadcaster],
) -> None:
    client, thread_id, recorder = setup_with_broadcaster
    resp = await client.post(
        f"/chat/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "user",
                "id": "u_bob",
                "name": "Bob",
                "metadata": {},
            }
        },
    )
    assert resp.status_code == 201
    assert len(recorder.thread_invited) == 1
    frame = recorder.thread_invited[0]
    assert frame.thread.id == thread_id
    assert frame.added_member.id == "u_bob"
    assert frame.added_by.id == "u_alice"


async def test_create_thread_does_not_emit_thread_invited_self(
    setup_with_broadcaster: tuple[AsyncClient, str, RecordingBroadcaster],
) -> None:
    # The setup_with_broadcaster fixture already POSTs /threads which auto-adds alice.
    # No thread_invited should have been emitted for the self-add.
    _, _, recorder = setup_with_broadcaster
    assert recorder.thread_invited == []


async def test_publish_thread_invited_short_circuits_on_self_add(
    clean_db: asyncpg.Pool,
) -> None:
    # Pins the guard in ChatServer.publish_thread_invited that skips self-adds,
    # independently of callers (rest/threads.create_thread bypasses this helper,
    # so the existing end-to-end test cannot detect a regression here).
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    recorder = RecordingBroadcaster()
    chat_server = ChatServer(store=store, authenticate=auth, broadcaster=recorder)

    now = datetime.now(UTC)
    thread = Thread(
        id="th_x",
        tenant={},
        metadata={},
        created_at=now,
        updated_at=now,
    )

    await chat_server.publish_thread_invited(thread, added_member=alice, added_by=alice)

    assert recorder.thread_invited == []


async def test_remove_member(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    await client.post(
        f"/chat/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "user",
                "id": "u_bob",
                "name": "Bob",
                "metadata": {},
            }
        },
    )
    resp = await client.delete(f"/chat/threads/{thread_id}/members/u_bob")
    assert resp.status_code == 204

    list_resp = await client.get(f"/chat/threads/{thread_id}/members")
    ids = {m["identity_id"] for m in list_resp.json()}
    assert ids == {"u_alice"}
