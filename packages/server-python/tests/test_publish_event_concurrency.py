from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from rfnry_chat_protocol import Identity, MessageEvent, TextPart, Thread, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.memory.store import InMemoryChatStore


async def test_publish_event_runs_write_and_broadcast_concurrently() -> None:

    store = InMemoryChatStore()
    broadcaster = RecordingBroadcaster()

    original_append = store.append_event

    async def slow_append(event):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.05)
        return await original_append(event)

    store.append_event = slow_append  # type: ignore[method-assign]

    original_broadcast = broadcaster.broadcast_event

    async def slow_broadcast(event, **kwargs):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.05)
        return await original_broadcast(event, **kwargs)

    broadcaster.broadcast_event = slow_broadcast  # type: ignore[method-assign]

    async def auth(_h: HandshakeData) -> Identity:
        return UserIdentity(id="u_alice", name="Alice")

    server = ChatServer(store=store, broadcaster=broadcaster, authenticate=auth)

    now = datetime.now(UTC)
    thread = await store.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))

    event = MessageEvent(
        id="evt_1",
        thread_id=thread.id,
        author=UserIdentity(id="u_alice", name="Alice"),
        created_at=datetime.now(UTC),
        content=[TextPart(text="hi")],
    )

    start = time.monotonic()
    await server.publish_event(event, thread=thread)
    elapsed = time.monotonic() - start

    assert elapsed < 0.08, f"publish_event took {elapsed:.3f}s — looks serial (would be ~0.1s)"
