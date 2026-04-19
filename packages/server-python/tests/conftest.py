from __future__ import annotations

import os
import pathlib
from collections.abc import AsyncIterator

import asyncpg
import pytest

DEFAULT_DATABASE_URL = "postgresql://rfnry_chat:rfnry_chat@localhost:55432/rfnry_chat_test"

SCHEMA_SQL = (
    pathlib.Path(__file__).resolve().parents[1] / "src" / "rfnry_chat_server" / "store" / "postgres" / "schema.sql"
).read_text()


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


@pytest.fixture(scope="session")
async def pg_pool() -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=4)
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def clean_db(pg_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    async with pg_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE thread_members, events, runs, threads RESTART IDENTITY CASCADE")
    yield pg_pool
