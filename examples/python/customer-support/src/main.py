from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rfnry_chat_server import InMemoryChatStore

from src.agent import create_chat_client
from src.chat import create_chat_server

PORT = 8000

chat_server = create_chat_server(store=InMemoryChatStore())


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    await chat_server.start()
    print("chat server running (in-memory, no auth)")

    chat_client = create_chat_client(f"http://127.0.0.1:{PORT}")
    agent_task = asyncio.create_task(chat_client.run())
    print("agent scheduled")

    try:
        yield
    finally:
        agent_task.cancel()
        try:
            await asyncio.wait_for(agent_task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        await chat_server.stop()


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
