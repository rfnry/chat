"""End-to-end smoke test for the run lifecycle fix.

Scenario: one user + three assistant clients all joined to the same thread.
Every assistant registers a role-filtering `on_message` emitter that only
yields when the author.role is "user". The user sends a single message.

Expected event counts observed on the thread's event log:

  - 3 `run.started`   (one per agent, because each agent's handler yields
                        exactly one reply)
  - 3 `run.completed` (one per agent)
  - 3 assistant `message` events (the actual replies)

Before the fix: the dispatcher called begin_run/end_run unconditionally,
so the "other two" agents in each fanout also produced empty runs. With
three agents, each user message caused 3 handlers to fire * (1 real yield
+ 2 early returns) — but the structure of the bug report observed 4
run.started + 9 run.completed due to interaction with the server-side
find_active_run reuse and the non-idempotent end_run.

This test is the regression pin. It uses the real socket + REST stack
against a Postgres-backed ChatServer in the same process.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from rfnry_chat_protocol import AssistantIdentity, Identity, TextPart, UserIdentity
from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.handler.send import HandlerSend

DEFAULT_DATABASE_URL = "postgresql://rfnry_chat:rfnry_chat@localhost:55432/rfnry_chat_test"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


USER = UserIdentity(id="u_alice", name="Alice")
AGENT_A = AssistantIdentity(id="agent-a", name="Agent A")
AGENT_B = AssistantIdentity(id="agent-b", name="Agent B")
AGENT_C = AssistantIdentity(id="agent-c", name="Agent C")
_IDENTITIES_BY_ID: dict[str, Identity] = {
    USER.id: USER,
    AGENT_A.id: AGENT_A,
    AGENT_B.id: AGENT_B,
    AGENT_C.id: AGENT_C,
}


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


@pytest.fixture
async def multi_agent_server(
    clean_db: asyncpg.Pool,
) -> AsyncIterator[tuple[str, ChatServer]]:
    store = PostgresChatStore(pool=clean_db)

    async def auth(handshake: HandshakeData) -> Identity:
        identity_id: str | None = None
        if isinstance(handshake.auth, dict):
            raw = handshake.auth.get("identity_id")
            if isinstance(raw, str):
                identity_id = raw
        if identity_id is None:
            header_val = handshake.headers.get("x-identity-id")
            if isinstance(header_val, str):
                identity_id = header_val
        if identity_id in _IDENTITIES_BY_ID:
            return _IDENTITIES_BY_ID[identity_id]
        return USER

    chat_server = ChatServer(store=store, authenticate=auth)

    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    asgi = chat_server.mount_socketio(app)

    live = _LiveServer(asgi)
    base = await live.start()
    try:
        yield base, chat_server
    finally:
        await live.stop()


def _authenticate_as(identity_id: str) -> Any:
    async def _authenticate() -> dict[str, Any]:
        return {
            "auth": {"identity_id": identity_id},
            "headers": {"x-identity-id": identity_id},
        }

    return _authenticate


async def _create_thread_with_members(base: str, members: list[Identity]) -> str:
    async with httpx.AsyncClient(base_url=base, headers={"x-identity-id": USER.id}) as http:
        create = await http.post("/chat/threads", json={"tenant": {}, "metadata": {"kind": "channel"}})
        assert create.status_code == 201, create.text
        thread_id = create.json()["id"]
        for member in members:
            resp = await http.post(
                f"/chat/threads/{thread_id}/members",
                json={"identity": member.model_dump(mode="json")},
            )
            assert resp.status_code in (200, 201), resp.text
    return thread_id


async def test_three_agent_channel_user_message_produces_3_runs(
    multi_agent_server: tuple[str, ChatServer],
) -> None:
    """Smoke test for the team-communication fanout. One message from Alice
    into a 3-agent channel produces exactly 3 run.started and 3 run.completed
    frames — one real run per agent, zero empty runs from the role-filter
    early-returns on sibling agents' fanout."""
    base, chat_server = multi_agent_server

    thread_id = await _create_thread_with_members(base, [USER, AGENT_A, AGENT_B, AGENT_C])

    # User client observes all events (including run.started / run.completed
    # frames) and counts them. The client passes `all_events=True` on the
    # handler so the default self/recipient filter does not drop run frames.
    user_client = ChatClient(base_url=base, identity=USER, authenticate=_authenticate_as(USER.id))
    agent_a = ChatClient(base_url=base, identity=AGENT_A, authenticate=_authenticate_as(AGENT_A.id))
    agent_b = ChatClient(base_url=base, identity=AGENT_B, authenticate=_authenticate_as(AGENT_B.id))
    agent_c = ChatClient(base_url=base, identity=AGENT_C, authenticate=_authenticate_as(AGENT_C.id))

    received: list[dict[str, Any]] = []
    last_event = asyncio.Event()

    @user_client.on("*", all_events=True)
    async def observe(ctx: HandlerContext, _send: HandlerSend) -> None:
        received.append({"type": ctx.event.type, "author": ctx.event.author.id})
        last_event.set()

    # Each agent registers a classic role-filter emitter: it early-returns on
    # non-user messages, which is the code path that used to spuriously
    # trigger begin_run / end_run under the old dispatcher.
    def _register_agent(client: ChatClient, reply_text: str) -> None:
        @client.on_message()
        async def respond(ctx: HandlerContext, send: HandlerSend):
            if ctx.event.author.role != "user":
                return
            yield send.message(content=[TextPart(text=reply_text)])

    _register_agent(agent_a, "A: got it")
    _register_agent(agent_b, "B: got it")
    _register_agent(agent_c, "C: got it")

    try:
        await user_client.connect()
        await agent_a.connect()
        await agent_b.connect()
        await agent_c.connect()

        await user_client.join_thread(thread_id)
        await agent_a.join_thread(thread_id)
        await agent_b.join_thread(thread_id)
        await agent_c.join_thread(thread_id)

        # User sends one message.
        await user_client.send_message(thread_id=thread_id, content=[TextPart(text="hello team")])

        # Wait until activity quiesces. We expect:
        #   1 user message + 3 agent messages + 3 run.started + 3 run.completed
        #   = 10 events.
        async def _quiesced() -> bool:
            # Sample count at T and T+150ms; if stable, assume done.
            n1 = len(received)
            await asyncio.sleep(0.15)
            return len(received) == n1 and n1 >= 10

        for _ in range(60):
            if await _quiesced():
                break

        types = [e["type"] for e in received]
        run_started = [e for e in received if e["type"] == "run.started"]
        run_completed = [e for e in received if e["type"] == "run.completed"]
        messages = [e for e in received if e["type"] == "message"]

        assert len(run_started) == 3, f"expected 3 run.started, got {len(run_started)}; full stream: {types}"
        assert len(run_completed) == 3, f"expected 3 run.completed, got {len(run_completed)}; full stream: {types}"
        # 1 user message + 3 agent replies.
        assert len(messages) == 4, f"expected 4 messages (1 user + 3 agents), got {len(messages)}; full stream: {types}"
    finally:
        await user_client.disconnect()
        await agent_a.disconnect()
        await agent_b.disconnect()
        await agent_c.disconnect()


pytestmark = pytest.mark.asyncio
