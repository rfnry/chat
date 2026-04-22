from __future__ import annotations

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from rfnry_chat_protocol import AssistantIdentity, Run, Thread, UserIdentity

from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def store(clean_db: asyncpg.Pool) -> PostgresChatStore:
    s = PostgresChatStore(pool=clean_db)
    now = datetime.now(UTC)
    await s.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    return s


async def _seed(store: PostgresChatStore, run_id: str, started_at: datetime, status: str) -> Run:
    run = Run(
        id=run_id,
        thread_id="th_1",
        actor=AssistantIdentity(id=f"a_{run_id}", name="Helper"),
        triggered_by=UserIdentity(id="u1", name="Alice"),
        status="pending",
        started_at=started_at,
    )
    created = await store.create_run(run)
    if status != "pending":
        await store.update_run_status(run_id, status)  # type: ignore[arg-type]
    return created


async def test_finds_runs_older_than_threshold(store: PostgresChatStore) -> None:
    old = datetime.now(UTC) - timedelta(minutes=10)
    recent = datetime.now(UTC)
    await _seed(store, "run_old", old, "running")
    await _seed(store, "run_recent", recent, "running")

    threshold = datetime.now(UTC) - timedelta(minutes=5)
    stale = await store.find_runs_started_before(
        threshold=threshold,
    )
    assert [r.id for r in stale] == ["run_old"]


async def test_excludes_completed_runs(store: PostgresChatStore) -> None:
    old = datetime.now(UTC) - timedelta(minutes=10)
    await _seed(store, "run_done", old, "completed")
    threshold = datetime.now(UTC) - timedelta(minutes=5)
    stale = await store.find_runs_started_before(
        threshold=threshold,
    )
    assert stale == []


async def test_honors_limit(store: PostgresChatStore) -> None:
    old = datetime.now(UTC) - timedelta(minutes=10)
    for i in range(5):
        await _seed(store, f"run_{i}", old - timedelta(seconds=i), "running")
    threshold = datetime.now(UTC) - timedelta(minutes=5)
    stale = await store.find_runs_started_before(
        threshold=threshold,
        limit=3,
    )
    assert len(stale) == 3


async def test_find_runs_started_before_uses_partial_index(clean_db: asyncpg.Pool) -> None:
    """Regression for R13: the sweep query's WHERE clause must match the
    runs_active_started partial index predicate literally so the planner
    picks the index.  ANY($1::text[]) prevents plan-time evaluation and
    silently falls back to a sequential scan; the literal IN list matches
    the index predicate exactly."""
    async with clean_db.acquire() as conn:
        rows = await conn.fetch(
            "EXPLAIN SELECT * FROM runs "
            "WHERE status IN ('pending', 'running') AND started_at < $1 "
            "ORDER BY started_at LIMIT 100",
            datetime.now(UTC),
        )
    plan_text = "\n".join(r["QUERY PLAN"] for r in rows)
    assert "runs_active_started" in plan_text, (
        f"watchdog sweep must use runs_active_started partial index; got:\n{plan_text}"
    )
