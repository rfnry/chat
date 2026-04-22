from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel
from rfnry_chat_protocol import TextPart, UserIdentity

from src.agent import build_pool
from src.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("monitoring-assistant.main")


class PingUserRequest(BaseModel):
    message: str
    user_id: str | None = None
    user_name: str | None = None
    thread_id: str | None = None
    chat_server_url: str | None = None


pool = build_pool()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await pool.close_all()


app = FastAPI(title="monitoring-assistant", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent/ping-user")
async def ping_user(body: PingUserRequest) -> dict[str, str]:
    base_url = body.chat_server_url or settings.DEFAULT_CHAT_SERVER_URL
    client = await pool.get_or_connect(base_url)

    user = None
    if body.user_id is not None:
        user = UserIdentity(id=body.user_id, name=body.user_name or body.user_id)

    thread, event = await client.open_thread_with(
        message=[TextPart(text=body.message)],
        invite=user,
        thread_id=body.thread_id,
    )
    logger.info("pinged user=%s thread=%s event=%s", body.user_id, thread.id, event.id)
    return {"thread_id": thread.id, "event_id": event.id}
