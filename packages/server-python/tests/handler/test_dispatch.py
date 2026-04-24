from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import asyncpg
import pytest
from rfnry_chat_protocol import (
    Identity,
    MessageEvent,
    ReasoningEvent,
    SystemIdentity,
    TextPart,
    Thread,
    ToolCall,
    ToolCallEvent,
    UserIdentity,
)

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.handler.context import HandlerContext
from rfnry_chat_server.handler.send import HandlerSend
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def setup(
    clean_db: asyncpg.Pool,
) -> tuple[ChatServer, RecordingBroadcaster, str]:
    store = PostgresChatStore(pool=clean_db)
    rec = RecordingBroadcaster()
    alice = UserIdentity(id="u_alice", name="Alice")

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ChatServer(store=store, authenticate=auth, broadcaster=rec)
    now = datetime.now(UTC)
    await store.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    return server, rec, "th_1"


async def _drain_background_tasks() -> None:
    for _ in range(10):
        await asyncio.sleep(0.05)
    tasks = [t for t in asyncio.all_tasks() if not t.done() and t is not asyncio.current_task()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _user_message(thread_id: str, text: str, evt_id: str = "evt_msg") -> MessageEvent:
    return MessageEvent(
        id=evt_id,
        thread_id=thread_id,
        author=UserIdentity(id="u_alice", name="Alice"),
        created_at=datetime.now(UTC),
        content=[TextPart(text=text)],
    )


def _user_reasoning(thread_id: str, text: str, evt_id: str = "evt_r") -> ReasoningEvent:
    return ReasoningEvent(
        id=evt_id,
        thread_id=thread_id,
        author=UserIdentity(id="u_alice", name="Alice"),
        created_at=datetime.now(UTC),
        content=text,
    )


def _user_tool_call(thread_id: str, name: str, args: dict) -> ToolCallEvent:
    return ToolCallEvent(
        id="evt_tc",
        thread_id=thread_id,
        author=UserIdentity(id="u_alice", name="Alice"),
        created_at=datetime.now(UTC),
        tool=ToolCall(id="call_1", name=name, arguments=args),
    )


async def test_message_observer_fires(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    server, _, thread_id = setup
    seen: list[MessageEvent] = []

    @server.on("message")
    async def handler(ctx: HandlerContext, _send: HandlerSend) -> None:
        seen.append(ctx.event)  # type: ignore[arg-type]

    await server.publish_event(_user_message(thread_id, "hello"))
    await _drain_background_tasks()
    assert len(seen) == 1
    assert seen[0].author.id == "u_alice"


async def test_message_emitter_publishes_with_system_author(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    server, rec, thread_id = setup

    @server.on("message")
    async def handler(_ctx: HandlerContext, send: HandlerSend):
        yield send.reasoning("processing")

    await server.publish_event(_user_message(thread_id, "please think"))
    await _drain_background_tasks()

    reasoning = [e for e in rec.events if e.type == "reasoning"]
    assert len(reasoning) == 1
    assert reasoning[0].author.role == "system"


async def test_tool_call_with_in_run_wraps_run(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    server, rec, thread_id = setup

    @server.on_tool_call("ping")
    async def handler(ctx: HandlerContext, send: HandlerSend):
        yield send.tool_result(ctx.event.tool.id, result={"pong": True})  # type: ignore[union-attr]

    await server.publish_event(_user_tool_call(thread_id, "ping", {}))
    await _drain_background_tasks()

    types = [e.type for e in rec.events]
    assert "run.started" in types
    assert "tool.result" in types
    assert "run.completed" in types

    results = [e for e in rec.events if e.type == "tool.result"]
    assert results[0].author.role == "system"
    assert results[0].tool.result == {"pong": True}  # type: ignore[union-attr]


async def test_chain_depth_cap_stops_runaway(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    server, rec, thread_id = setup

    @server.on("reasoning")
    async def loop_forever(_ctx: HandlerContext, send: HandlerSend):
        yield send.reasoning("more")

    await server.publish_event(_user_reasoning(thread_id, "start"))
    await _drain_background_tasks()

    reasoning_by_system = [e for e in rec.events if e.type == "reasoning" and e.author.role == "system"]
    assert 0 < len(reasoning_by_system) <= 8


async def test_system_authored_events_do_not_retrigger(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    server, rec, thread_id = setup
    call_count = {"value": 0}

    @server.on("message")
    async def handler(_ctx: HandlerContext, send: HandlerSend):
        call_count["value"] += 1
        yield send.message(content=[TextPart(text="reply")])

    await server.publish_event(_user_message(thread_id, "hi"))
    await _drain_background_tasks()
    assert call_count["value"] == 1
    system_messages = [e for e in rec.events if e.type == "message" and e.author.role == "system"]
    assert len(system_messages) == 1


async def test_system_identity_override(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    rec = RecordingBroadcaster()

    async def auth(_h: HandshakeData) -> Identity:
        return UserIdentity(id="u_alice", name="Alice")

    custom_system = SystemIdentity(id="srv_alpha", name="Alpha Server")
    server = ChatServer(
        store=store,
        authenticate=auth,
        broadcaster=rec,
        system_identity=custom_system,
    )
    now = datetime.now(UTC)
    await store.create_thread(Thread(id="th_sys", tenant={}, metadata={}, created_at=now, updated_at=now))

    @server.on("message")
    async def handler(_ctx: HandlerContext, send: HandlerSend):
        yield send.reasoning("hi")

    await server.publish_event(_user_message("th_sys", "msg"))
    await _drain_background_tasks()

    reasoning = [e for e in rec.events if e.type == "reasoning"]
    assert reasoning[0].author.id == "srv_alpha"
