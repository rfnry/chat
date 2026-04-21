from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rfnry_chat_server import InMemoryChatStore

from src.chat import create_chat_server

Workspace = Literal["legal", "medical"]

WORKSPACE: Workspace = os.environ.get("WORKSPACE", "legal")  # type: ignore[assignment]
if WORKSPACE not in ("legal", "medical"):
    raise ValueError(f"WORKSPACE must be 'legal' or 'medical'; got {WORKSPACE!r}")

PORT = int(os.environ.get("PORT", "8001"))

if WORKSPACE == "legal":
    from src.agent_legal import create_chat_client
else:
    from src.agent_medical import create_chat_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(f"org.{WORKSPACE}.main")

chat_server = create_chat_server(store=InMemoryChatStore(), workspace=WORKSPACE)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    await chat_server.start()
    logger.info("chat server running workspace=%s port=%d (in-memory, no auth)", WORKSPACE, PORT)

    chat_client = create_chat_client(f"http://127.0.0.1:{PORT}")
    agent_task = asyncio.create_task(chat_client.run())

    try:
        yield
    finally:
        agent_task.cancel()
        try:
            await asyncio.wait_for(agent_task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        await chat_server.stop()


app = FastAPI(title=f"org-workspace-{WORKSPACE}", lifespan=lifespan)
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
    return {"status": "ok", "workspace": WORKSPACE}


asgi = chat_server.mount_socketio(app)
