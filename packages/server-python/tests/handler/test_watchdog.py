from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import asyncpg
import pytest
from rfnry_chat_protocol import AssistantIdentity, Identity, Thread, UserIdentity

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
    alice = UserIdentity(id="u_alice", name="Alice")

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ChatServer(
        store=store,
        authenticate=auth,
        broadcaster=rec,
        run_timeout_seconds=1,
        watchdog_interval_seconds=0.1,
    )
    now = datetime.now(UTC)
    await store.create_thread(
        Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now)
    )
    return server, rec, "th_1"


async def test_watchdog_times_out_stale_running_run(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    server, rec, thread_id = setup
    thread = await server.store.get_thread(thread_id)
    assert thread is not None
    actor = AssistantIdentity(id="a_stuck", name="Stuck")
    user = UserIdentity(id="u_alice", name="Alice")

    run = await server.begin_run(
        thread=thread,
        actor=actor,
        triggered_by=user,
        idempotency_key=None,
    )
    assert run.status == "running"

    await server.start()
    try:
        for _ in range(50):
            if any(e.type == "run.failed" for e in rec.events):
                break
            await asyncio.sleep(0.1)
        refreshed = await server.store.get_run(run.id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.error is not None
        assert refreshed.error.code == "timeout"
        assert any(e.type == "run.failed" for e in rec.events)
    finally:
        await server.stop()


async def test_watchdog_leaves_fresh_run_alone(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    server, _, thread_id = setup
    server.run_timeout_seconds = 60
    thread = await server.store.get_thread(thread_id)
    assert thread is not None
    actor = AssistantIdentity(id="a_ok", name="Active")
    user = UserIdentity(id="u_alice", name="Alice")

    run = await server.begin_run(
        thread=thread,
        actor=actor,
        triggered_by=user,
        idempotency_key=None,
    )

    await server.start()
    try:
        await asyncio.sleep(0.4)
        refreshed = await server.store.get_run(run.id)
        assert refreshed is not None
        assert refreshed.status == "running"
    finally:
        await server.stop()


async def test_start_is_idempotent(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    server, _, _ = setup
    await server.start()
    try:
        first = server._watchdog_task
        await server.start()
        assert server._watchdog_task is first
    finally:
        await server.stop()


async def test_stop_without_start_is_noop(
    setup: tuple[ChatServer, RecordingBroadcaster, str],
) -> None:
    server, _, _ = setup
    await server.stop()
