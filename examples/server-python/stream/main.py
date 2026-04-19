from __future__ import annotations

import asyncio
import os

import asyncpg
import uvicorn
from anthropic import AsyncAnthropic
from fastapi import FastAPI

from rfnry_chat_server import (
    HandshakeData,
    PostgresChatStore,
    TextPart,
    ChatServer,
    UserIdentity,
)


async def authenticate(handshake: HandshakeData) -> UserIdentity | None:
    token = handshake.headers.get("authorization", "")
    if not token.startswith("Bearer "):
        return None
    user_id = token.removeprefix("Bearer ").strip()
    if not user_id:
        return None
    return UserIdentity(id=user_id, name=user_id)


async def main() -> None:
    pool = await asyncpg.create_pool(os.environ.get("DATABASE_URL", "postgresql://rrcp:rrcp@localhost:55432/rrcp_test"))
    client = AsyncAnthropic()

    thread_server = ChatServer(
        store=PostgresChatStore(pool=pool),
        authenticate=authenticate,
    )

    @thread_server.assistant("claude")
    async def claude(ctx, send):
        history = await ctx.events()
        messages = []
        for event in history:
            if event.type != "message":
                continue
            role = "user" if event.author.role == "user" else "assistant"
            text = "".join(p.text for p in event.content if isinstance(p, TextPart))
            if text:
                messages.append({"role": role, "content": text})
        if not messages:
            return

        async with send.message_stream() as stream:
            async with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=1024,
                messages=messages,
            ) as result:
                async for chunk in result.text_stream:
                    await stream.append(chunk)

    app = FastAPI()
    app.state.thread_server = thread_server
    app.include_router(thread_server.router, prefix="/acp")
    asgi = thread_server.mount_socketio(app)

    config = uvicorn.Config(asgi, host="0.0.0.0", port=8000, loop="asyncio")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
