from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from rfnry_chat_protocol import Run, Thread, UserIdentity

from rfnry_chat_server import ChatServer
from rfnry_chat_server.store.memory.store import InMemoryChatStore


@pytest.mark.asyncio
async def test_watchdog_drains_backlog_beyond_batch_size() -> None:
    store = InMemoryChatStore()
    server = ChatServer(
        store=store,
        run_timeout_seconds=1,
        watchdog_interval_seconds=0.05,
        watchdog_batch_size=5,
    )
    # Seed 12 stale runs (started 10s ago), each with its own thread.
    alice = UserIdentity(id="u_alice", name="Alice")
    stale_started_at = datetime.now(UTC) - timedelta(seconds=10)
    for i in range(12):
        thread = Thread(
            id=f"th_{i}",
            tenant={},
            metadata={},
            created_at=stale_started_at,
            updated_at=stale_started_at,
        )
        await store.create_thread(thread, caller_identity_id=alice.id)
        await store.add_member(thread.id, alice, added_by=alice)
        run = Run(
            id=f"run_{i}",
            thread_id=thread.id,
            actor=alice,
            triggered_by=alice,
            status="running",
            started_at=stale_started_at,
        )
        await store.create_run(run)

    # One sweep should drain all 12, not just batch_size=5.
    await server._sweep_stale_runs()

    for i in range(12):
        run = await store.get_run(f"run_{i}")
        assert run is not None
        assert run.status == "failed", f"run_{i} still {run.status}"


@pytest.mark.asyncio
async def test_watchdog_batch_size_constructor_param_propagates() -> None:
    """ChatServer honors watchdog_batch_size as a ctor kwarg."""
    server = ChatServer(store=InMemoryChatStore(), watchdog_batch_size=7)
    assert server.watchdog_batch_size == 7


@pytest.mark.asyncio
async def test_watchdog_batch_size_default() -> None:
    server = ChatServer(store=InMemoryChatStore())
    assert server.watchdog_batch_size == 100
