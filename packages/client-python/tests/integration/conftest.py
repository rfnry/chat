from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
import uvicorn
from fastapi import FastAPI
from rfnry_chat_protocol import AssistantIdentity, Identity, UserIdentity
from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore

DEFAULT_DATABASE_URL = "postgresql://rfnry_chat:rfnry_chat@localhost:55432/rfnry_chat_test"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def _skip_without_db(reason: str) -> None:
    pytest.skip(reason, allow_module_level=False)


@pytest.fixture(scope="session")
async def pg_pool() -> AsyncIterator[asyncpg.Pool]:
    try:
        pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=4)
    except (OSError, asyncpg.exceptions.PostgresError) as exc:
        pytest.skip(f"postgres unavailable: {exc}", allow_module_level=True)
    assert pool is not None
    await PostgresChatStore(pool=pool).ensure_schema()
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def clean_db(pg_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    async with pg_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE thread_members, events, runs, threads RESTART IDENTITY CASCADE")
    yield pg_pool


class _LiveServer:
    def __init__(self, app: Any) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off")
        self._server = uvicorn.Server(config)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> str:
        self._task = asyncio.create_task(self._server.serve())
        for _ in range(500):
            if self._server.started:
                break
            await asyncio.sleep(0.01)
        assert self._server.started
        sock = self._server.servers[0].sockets[0]
        port = sock.getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, timeout=5)


DEFAULT_USER = UserIdentity(id="u_alice", name="Alice")
DEFAULT_ASSISTANT = AssistantIdentity(id="a_helper", name="Helper")


@pytest.fixture
async def live_server(
    clean_db: asyncpg.Pool,
) -> AsyncIterator[tuple[str, ChatServer]]:
    store = PostgresChatStore(pool=clean_db)

    async def auth(handshake: HandshakeData) -> Identity:
        identity_id: str | None = None
        if isinstance(handshake.auth, dict):
            raw = handshake.auth.get("identity_id")
            if isinstance(raw, str):
                identity_id = raw
        # REST calls carry no socket-style auth payload; fall back to a
        # test-only header so multi-identity tests can distinguish callers.
        if identity_id is None:
            header_val = handshake.headers.get("x-identity-id")
            if isinstance(header_val, str):
                identity_id = header_val
        if identity_id == DEFAULT_ASSISTANT.id:
            return DEFAULT_ASSISTANT
        return DEFAULT_USER

    chat_server = ChatServer(store=store, authenticate=auth)

    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    asgi = chat_server.mount(app)

    live = _LiveServer(asgi)
    base = await live.start()
    try:
        yield base, chat_server
    finally:
        await live.stop()
