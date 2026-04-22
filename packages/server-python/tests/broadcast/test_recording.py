from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import (
    AssistantIdentity,
    Identity,
    MessageEvent,
    TextPart,
    Thread,
    ThreadInvitedFrame,
    UserIdentity,
)

from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def setup(
    clean_db: asyncpg.Pool,
) -> tuple[ChatServer, RecordingBroadcaster, str]:
    store = PostgresChatStore(pool=clean_db)
    rec = RecordingBroadcaster()

    async def auth(_h: HandshakeData) -> Identity:
        return UserIdentity(id="u1", name="Alice")

    chat_server = ChatServer(store=store, authenticate=auth, broadcaster=rec)
    now = datetime.now(UTC)
    await store.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    return chat_server, rec, "th_1"


async def test_publish_event_calls_broadcaster(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    chat_server, rec, thread_id = setup
    event = MessageEvent(
        id="evt_1",
        thread_id=thread_id,
        author=UserIdentity(id="u1", name="Alice"),
        created_at=datetime.now(UTC),
        content=[TextPart(text="hi")],
    )
    await chat_server.publish_event(event)
    assert len(rec.events) == 1
    assert rec.events[0].id == "evt_1"


async def test_recording_broadcaster_records_namespace() -> None:
    rec = RecordingBroadcaster()
    event1 = MessageEvent(
        id="evt_1",
        thread_id="th_1",
        author=UserIdentity(id="u1", name="Alice"),
        created_at=datetime.now(UTC),
        content=[TextPart(text="hi")],
    )
    event2 = MessageEvent(
        id="evt_2",
        thread_id="th_1",
        author=UserIdentity(id="u1", name="Alice"),
        created_at=datetime.now(UTC),
        content=[TextPart(text="bye")],
    )
    await rec.broadcast_event(event1, namespace="/A")
    await rec.broadcast_event(event2)
    assert rec.events_with_namespace == [(event1, "/A"), (event2, None)]


async def test_rest_message_send_triggers_broadcast(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresChatStore(pool=clean_db)
    rec = RecordingBroadcaster()
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth, broadcaster=rec)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={"client_id": "c1", "content": [{"type": "text", "text": "hi"}]},
    )

    assert len(rec.events) == 1
    assert rec.events[0].thread_id == thread_id
    assert len(rec.members_updated) == 1


async def test_recording_broadcaster_records_thread_invited() -> None:
    now = datetime.now(UTC)
    frame = ThreadInvitedFrame(
        thread=Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now),
        added_member=UserIdentity(id="u_alice", name="Alice", metadata={}),
        added_by=AssistantIdentity(id="a_bot", name="Bot", metadata={}),
    )
    b = RecordingBroadcaster()
    await b.broadcast_thread_invited(frame, namespace="/A")

    assert b.thread_invited == [frame]
    assert b.thread_invited_with_namespace == [(frame, "/A")]
