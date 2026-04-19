from __future__ import annotations

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rfnry_chat_server.protocol.content import TextPart
from rfnry_chat_server.protocol.identity import Identity, UserIdentity
from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


async def test_full_chat_with_assistant(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth, run_timeout_seconds=5)

    @chat_server.assistant("a1")
    async def helper(ctx, send):
        history = await ctx.events()
        last_user = next((e for e in reversed(history) if e.author.role == "user"), None)
        echo = "I heard nothing"
        if last_user is not None and getattr(last_user, "content", None):
            first_part = last_user.content[0]
            if hasattr(first_part, "text"):
                echo = f"You said: {first_part.text}"
        yield send.reasoning("looking at history")
        yield send.tool_call(name="echo", arguments={"input": echo}, id="call_x")
        yield send.tool_result(tool_id="call_x", result={"echo": echo})
        yield send.message(content=[TextPart(text=echo)])

    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    await client.post(
        f"/chat/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "assistant",
                "id": "a1",
                "name": "Helper",
                "metadata": {},
            }
        },
    )

    await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={
            "client_id": "u1",
            "content": [{"type": "text", "text": "hello world"}],
        },
    )

    invoke = await client.post(
        f"/chat/threads/{thread_id}/invocations",
        json={"assistant_ids": ["a1"]},
    )
    run_id = invoke.json()["runs"][0]["id"]
    await chat_server.executor.await_run(run_id)

    events = (await client.get(f"/chat/threads/{thread_id}/events")).json()["items"]
    types = [e["type"] for e in events]
    assert types == [
        "message",
        "run.started",
        "reasoning",
        "tool.call",
        "tool.result",
        "message",
        "run.completed",
    ]

    last_message = events[-2]
    assert last_message["author"]["id"] == "a1"
    assert last_message["content"][0]["text"] == "You said: hello world"
