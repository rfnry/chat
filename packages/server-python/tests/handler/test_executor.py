from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import asyncpg
import pytest

from rfnry_chat_server.handler.executor import RunExecutor
from rfnry_chat_server.protocol.content import TextPart
from rfnry_chat_server.protocol.identity import AssistantIdentity, UserIdentity
from rfnry_chat_server.protocol.thread import Thread
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def setup(
    clean_db: asyncpg.Pool,
) -> tuple[PostgresChatStore, RunExecutor, Thread]:
    store = PostgresChatStore(pool=clean_db)
    now = datetime.now(UTC)
    thread = await store.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    executor = RunExecutor(store=store, run_timeout_seconds=5)
    return store, executor, thread


def _user() -> UserIdentity:
    return UserIdentity(id="u1", name="Alice")


def _asst() -> AssistantIdentity:
    return AssistantIdentity(id="a1", name="Helper")


async def test_happy_path_yields_events(
    setup: tuple[PostgresChatStore, RunExecutor, Thread],
) -> None:
    store, executor, thread = setup

    async def handler(ctx, send):
        yield send.reasoning("thinking")
        yield send.message(content=[TextPart(text="done")])

    run = await executor.execute(thread, _asst(), _user(), handler)
    assert run.status == "pending"

    await executor.await_run(run.id)

    fresh = await store.get_run(run.id)
    assert fresh is not None
    assert fresh.status == "completed"

    page = await store.list_events("th_1", limit=50)
    types = [e.type for e in page.items]
    assert types == ["run.started", "reasoning", "message", "run.completed"]


async def test_handler_exception_emits_run_failed(
    setup: tuple[PostgresChatStore, RunExecutor, Thread],
) -> None:
    store, executor, thread = setup

    async def handler(ctx, send):
        yield send.reasoning("about to crash")
        raise RuntimeError("boom")

    run = await executor.execute(thread, _asst(), _user(), handler)
    await executor.await_run(run.id)

    fresh = await store.get_run(run.id)
    assert fresh is not None
    assert fresh.status == "failed"
    assert fresh.error is not None
    assert fresh.error.code == "handler_error"
    assert "boom" in fresh.error.message

    page = await store.list_events("th_1", limit=50)
    types = [e.type for e in page.items]
    assert types[0] == "run.started"
    assert types[-1] == "run.failed"


async def test_timeout_emits_run_failed(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    now = datetime.now(UTC)
    thread = await store.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    executor = RunExecutor(store=store, run_timeout_seconds=1)

    async def handler(ctx, send):
        await asyncio.sleep(3)
        yield send.message(content=[TextPart(text="never")])

    run = await executor.execute(thread, _asst(), _user(), handler)
    await executor.await_run(run.id)

    fresh = await store.get_run(run.id)
    assert fresh is not None
    assert fresh.status == "failed"
    assert fresh.error is not None
    assert fresh.error.code == "timeout"


async def test_cancel_emits_run_cancelled(
    setup: tuple[PostgresChatStore, RunExecutor, Thread],
) -> None:
    store, executor, thread = setup

    started = asyncio.Event()

    async def handler(ctx, send):
        started.set()
        await asyncio.sleep(10)
        yield send.message(content=[TextPart(text="never")])

    run = await executor.execute(thread, _asst(), _user(), handler)
    await asyncio.wait_for(started.wait(), timeout=2)
    await executor.cancel(run.id)
    await executor.await_run(run.id)

    fresh = await store.get_run(run.id)
    assert fresh is not None
    assert fresh.status == "cancelled"


async def test_idempotency_returns_existing(
    setup: tuple[PostgresChatStore, RunExecutor, Thread],
) -> None:
    store, executor, thread = setup

    async def handler(ctx, send):
        yield send.message(content=[TextPart(text="hi")])

    run1 = await executor.execute(thread, _asst(), _user(), handler, idempotency_key="key_1")
    await executor.await_run(run1.id)

    run2 = await executor.execute(thread, _asst(), _user(), handler, idempotency_key="key_1")
    assert run2.id == run1.id


async def test_concurrent_invoke_same_assistant_returns_existing(
    setup: tuple[PostgresChatStore, RunExecutor, Thread],
) -> None:
    store, executor, thread = setup

    started = asyncio.Event()

    async def slow(ctx, send):
        started.set()
        await asyncio.sleep(0.5)
        yield send.message(content=[TextPart(text="done")])

    run1 = await executor.execute(thread, _asst(), _user(), slow)
    await asyncio.wait_for(started.wait(), timeout=2)
    run2 = await executor.execute(thread, _asst(), _user(), slow)
    assert run2.id == run1.id

    await executor.await_run(run1.id)
