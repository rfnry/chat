from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rfnry_chat_server import ChatStore

from src.chat import create_chat_server
from src.agent import create_chat_client

from src.db import LazyStore, create_pool
from src.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cs.main")

store = LazyStore()
chat_server = create_chat_server(store=cast(ChatStore, store))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    pool = await create_pool(settings.DATABASE_URL)
    logger.info("db pool ready")
    store.bind(pool)
    await chat_server.start()
    logger.info("chat server running")

    chat_client = create_chat_client(f"http://127.0.0.1:{settings.PORT}")
    agent_task = asyncio.create_task(chat_client.run())
    logger.info("agent scheduled")

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
