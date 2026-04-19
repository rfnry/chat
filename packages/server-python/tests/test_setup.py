import asyncpg


async def test_pg_pool_connects(pg_pool: asyncpg.Pool) -> None:
    async with pg_pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
    assert result == 1
