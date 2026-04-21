from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rfnry_chat_server import ChatStore

from src.db import LazyStore, create_pool
from src.server import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("stock-tool.main")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://rfnry_chat:rfnry_chat@localhost:55432/rfnry_chat_test",
)

store = LazyStore()
chat_server = build(store=cast(ChatStore, store))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    pool = await create_pool(DATABASE_URL)
    logger.info("db pool ready")
    store.bind(pool)
    await chat_server.start()
    logger.info("chat server + watchdog running")
    try:
        yield
    finally:
        await chat_server.stop()
        await pool.close()
        logger.info("shutdown complete")


app = FastAPI(title="stock-tool", lifespan=lifespan)
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
