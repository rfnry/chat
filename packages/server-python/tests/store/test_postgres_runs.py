from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest
from rfnry_chat_protocol import AssistantIdentity, Run, RunError, Thread, UserIdentity

from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def store(clean_db: asyncpg.Pool) -> PostgresChatStore:
    s = PostgresChatStore(pool=clean_db)
    now = datetime.now(UTC)
    await s.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    return s


def _new_run(id: str = "run_1", idempotency_key: str | None = None) -> Run:
    return Run(
        id=id,
        thread_id="th_1",
        actor=AssistantIdentity(id="a1", name="Helper"),
        triggered_by=UserIdentity(id="u1", name="Alice"),
        status="pending",
        started_at=datetime.now(UTC),
        idempotency_key=idempotency_key,
    )


async def test_create_and_get_run(store: PostgresChatStore) -> None:
    created = await store.create_run(_new_run())
    assert created.id == "run_1"
    assert created.status == "pending"

    got = await store.get_run("run_1")
    assert got is not None
    assert got.actor.id == "a1"


async def test_update_run_status_to_running(store: PostgresChatStore) -> None:
    await store.create_run(_new_run())
    updated = await store.update_run_status("run_1", "running")
    assert updated.status == "running"
    assert updated.completed_at is None


async def test_update_run_status_to_completed_sets_completed_at(
    store: PostgresChatStore,
) -> None:
    await store.create_run(_new_run())
    updated = await store.update_run_status("run_1", "completed")
    assert updated.status == "completed"
    assert updated.completed_at is not None


async def test_update_run_status_failed_with_error(store: PostgresChatStore) -> None:
    await store.create_run(_new_run())
    err = RunError(code="handler_error", message="boom")
    updated = await store.update_run_status("run_1", "failed", error=err)
    assert updated.status == "failed"
    assert updated.error is not None
    assert updated.error.code == "handler_error"


async def test_find_run_by_idempotency_key(store: PostgresChatStore) -> None:
    await store.create_run(_new_run(idempotency_key="key_1"))
    found = await store.find_run_by_idempotency_key("th_1", "key_1")
    assert found is not None
    assert found.id == "run_1"

    missing = await store.find_run_by_idempotency_key("th_1", "nope")
    assert missing is None


async def test_find_active_run(store: PostgresChatStore) -> None:
    await store.create_run(_new_run())
    found = await store.find_active_run("th_1", actor_id="a1")
    assert found is not None
    assert found.id == "run_1"

    await store.update_run_status("run_1", "completed")
    after = await store.find_active_run("th_1", actor_id="a1")
    assert after is None


async def test_allows_multiple_active_runs_per_actor(
    store: PostgresChatStore,
) -> None:
    """The runs_active_per_actor partial unique index was dropped: concurrent
    begin_run calls from the same (thread, actor) must both succeed and
    produce distinct runs. Runs are observability envelopes, not per-actor
    locks — callers that want dedup pass an idempotency_key."""
    first = await store.create_run(_new_run(id="run_1"))
    second = await store.create_run(_new_run(id="run_2"))
    assert first.id == "run_1"
    assert second.id == "run_2"
    assert first.actor.id == second.actor.id
    assert first.status == "pending"
    assert second.status == "pending"


async def test_idempotency_key_partial_unique(store: PostgresChatStore) -> None:
    await store.create_run(_new_run(id="run_1", idempotency_key="key_a"))
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await store.create_run(_new_run(id="run_2", idempotency_key="key_a"))


async def test_runs_active_started_index_exists(clean_db: asyncpg.Pool) -> None:
    """Regression for R13: the watchdog sweep query (status IN
    ('pending','running') AND started_at < threshold) must be backed by a
    partial index. Without it, the sweep is a sequential scan over the
    full runs table and gets unusably slow under load."""
    s = PostgresChatStore(pool=clean_db)
    await s.ensure_schema()
    async with clean_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'runs' AND indexname = 'runs_active_started'
            """
        )
    assert len(rows) == 1, "runs_active_started partial index must exist"


async def test_runs_active_per_actor_index_is_absent(clean_db: asyncpg.Pool) -> None:
    """The runs_active_per_actor partial unique index was dropped: it turned
    truly concurrent begin_run calls for the same (thread, actor) into
    UniqueViolationErrors. ensure_schema must also drop the index from
    any database created against the old schema."""
    s = PostgresChatStore(pool=clean_db)
    await s.ensure_schema()
    async with clean_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'runs' AND indexname = 'runs_active_per_actor'
            """
        )
    assert len(rows) == 0, "runs_active_per_actor unique index must be absent"


async def test_create_run_returns_persisted_state_via_returning(
    store: PostgresChatStore,
) -> None:
    """Regression for R12.1: create_run must reflect the persisted DB state,
    not just the input. Today started_at is set in Python so input == output;
    this test pins the contract for future schema changes that might use
    DB-side defaults."""
    run = _new_run(id="run_r12")
    created = await store.create_run(run)

    refetched = await store.get_run(run.id)
    assert refetched is not None
    assert created.model_dump(mode="json") == refetched.model_dump(mode="json"), (
        "create_run's return value must equal what get_run reads back"
    )
