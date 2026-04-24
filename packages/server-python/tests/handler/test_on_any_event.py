from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rfnry_chat_protocol import MessageEvent, TextPart, Thread, UserIdentity

from rfnry_chat_server import ChatServer
from rfnry_chat_server.store.memory.store import InMemoryChatStore


@pytest.mark.asyncio
async def test_on_any_event_fires_for_every_event_type() -> None:
    store = InMemoryChatStore()
    server = ChatServer(store=store)
    alice = UserIdentity(id="u_alice", name="Alice")

    now = datetime.now(UTC)
    thread = await store.create_thread(
        Thread(id="th_x", tenant={}, metadata={}, created_at=now, updated_at=now),
        caller_identity_id=alice.id,
    )

    seen: list[str] = []

    @server.on_any_event()
    async def _tap(ctx, send) -> None:
        seen.append(ctx.event.type)

    evt = MessageEvent(
        id="evt_1",
        thread_id=thread.id,
        author=alice,
        created_at=now,
        content=[TextPart(text="hi")],
    )
    await server._handler_dispatcher.dispatch(evt, thread)
    assert seen == ["message"]
