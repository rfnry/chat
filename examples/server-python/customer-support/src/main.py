from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rfnry_chat_server import ChatStore

from src import agent
from src.db import LazyStore, create_pool
from src.server import build
from src.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cs.main")

store = LazyStore()
chat_server = build(store=cast(ChatStore, store))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    pool = await create_pool(settings.DATABASE_URL)
    logger.info("db pool ready")
    store.bind(pool)
    await chat_server.start()
    logger.info("chat server + watchdog running")

    base_url = f"http://127.0.0.1:{settings.PORT}"
    client = agent.build_client(base_url)

    agent_task = asyncio.create_task(_run_agent(client))
    logger.info("agent client scheduled connect to %s", base_url)

    try:
        yield
    finally:
        agent_task.cancel()
        try:
            await asyncio.wait_for(agent_task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        await chat_server.stop()
        await pool.close()
        logger.info("shutdown complete")


async def _run_agent(client) -> None:
    for _ in range(50):
        try:
            await client.connect()
            logger.info("agent connected")
            break
        except Exception as exc:
            logger.debug("agent connect retry: %s", exc)
            await asyncio.sleep(0.2)
    else:
        logger.error("agent failed to connect after retries")
        return

    try:
        await asyncio.Event().wait()
    finally:
        await client.disconnect()


app = FastAPI(title="cs-example", lifespan=lifespan)
app.state.chat_server = chat_server
app.include_router(chat_server.router, prefix="/chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


asgi = chat_server.mount_socketio(app)
