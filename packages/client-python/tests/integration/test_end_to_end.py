from __future__ import annotations

import asyncio
from typing import Any

import httpx
from rfnry_chat_protocol import AssistantIdentity, TextPart, UserIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.handler.send import HandlerSend

DEFAULT_USER = UserIdentity(id="u_alice", name="Alice")
DEFAULT_ASSISTANT = AssistantIdentity(id="a_helper", name="Helper")


async def _seed_thread_with_member(base: str, identity: dict[str, Any]) -> str:
    async with httpx.AsyncClient(base_url=base) as http:
        create = await http.post("/chat/threads", json={"tenant": {}})
        thread_id = create.json()["id"]
        await http.post(
            f"/chat/threads/{thread_id}/members",
            json={"identity": identity},
        )
    return thread_id


async def _wait_until(predicate, attempts: int = 50, delay: float = 0.05) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await asyncio.sleep(delay)
    return predicate()


async def test_client_joins_thread_and_receives_events(
    live_server: tuple[str, Any],
) -> None:
    base, _ = live_server
    thread_id = await _seed_thread_with_member(base, DEFAULT_ASSISTANT.model_dump(mode="json"))

    async def authenticate() -> dict[str, Any]:
        return {"auth": {"identity_id": DEFAULT_ASSISTANT.id}}

    client = ChatClient(
        base_url=base,
        identity=DEFAULT_ASSISTANT,
        authenticate=authenticate,
    )
    received: list[Any] = []

    @client.on_message()
    async def observe(ctx: HandlerContext, _send: HandlerSend) -> None:
        received.append(ctx.event)

    try:
        await client.connect()
        await client.join_thread(thread_id)

        async with httpx.AsyncClient(base_url=base) as http:
            await http.post(
                f"/chat/threads/{thread_id}/messages",
                json={"client_id": "c1", "content": [{"type": "text", "text": "hi"}]},
            )

        assert await _wait_until(lambda: len(received) >= 1)
        assert received[0].type == "message"
        assert received[0].author.id == DEFAULT_USER.id
    finally:
        await client.disconnect()


async def test_client_emits_reply_through_handler(
    live_server: tuple[str, Any],
) -> None:
    base, _ = live_server
    thread_id = await _seed_thread_with_member(base, DEFAULT_ASSISTANT.model_dump(mode="json"))

    async def authenticate() -> dict[str, Any]:
        return {"auth": {"identity_id": DEFAULT_ASSISTANT.id}}

    client = ChatClient(
        base_url=base,
        identity=DEFAULT_ASSISTANT,
        authenticate=authenticate,
    )
    seen: list[Any] = []

    @client.on_message()
    async def reply(_ctx: HandlerContext, send: HandlerSend):
        yield send.message(content=[TextPart(text="pong")])

    @client.on("message", all_events=True)
    async def audit(ctx: HandlerContext, _send: HandlerSend) -> None:
        seen.append(ctx.event)

    try:
        await client.connect()
        await client.join_thread(thread_id)

        async with httpx.AsyncClient(base_url=base) as http:
            await http.post(
                f"/chat/threads/{thread_id}/messages",
                json={
                    "client_id": "c_ping",
                    "content": [{"type": "text", "text": "ping"}],
                },
            )

        assert await _wait_until(lambda: any(e.type == "message" and e.author.id == DEFAULT_ASSISTANT.id for e in seen))
    finally:
        await client.disconnect()


async def test_client_run_wrap_emits_run_started_and_completed(
    live_server: tuple[str, Any],
) -> None:
    base, _ = live_server
    thread_id = await _seed_thread_with_member(base, DEFAULT_ASSISTANT.model_dump(mode="json"))

    async def authenticate() -> dict[str, Any]:
        return {"auth": {"identity_id": DEFAULT_ASSISTANT.id}}

    client = ChatClient(
        base_url=base,
        identity=DEFAULT_ASSISTANT,
        authenticate=authenticate,
    )
    seen_types: list[str] = []

    @client.on_message()
    async def reply(_ctx: HandlerContext, send: HandlerSend):
        yield send.message(content=[TextPart(text="ack")])

    @client.on("*", all_events=True)
    async def audit(ctx: HandlerContext, _send: HandlerSend) -> None:
        seen_types.append(ctx.event.type)

    try:
        await client.connect()
        await client.join_thread(thread_id)

        async with httpx.AsyncClient(base_url=base) as http:
            await http.post(
                f"/chat/threads/{thread_id}/messages",
                json={
                    "client_id": "c_trigger",
                    "content": [{"type": "text", "text": "trigger"}],
                },
            )

        assert await _wait_until(lambda: "run.completed" in seen_types)
        assert "run.started" in seen_types
        assert "run.completed" in seen_types
    finally:
        await client.disconnect()


async def test_client_streams_message(live_server: tuple[str, Any]) -> None:
    base, _ = live_server
    thread_id = await _seed_thread_with_member(base, DEFAULT_ASSISTANT.model_dump(mode="json"))

    async def authenticate() -> dict[str, Any]:
        return {"auth": {"identity_id": DEFAULT_ASSISTANT.id}}

    client = ChatClient(
        base_url=base,
        identity=DEFAULT_ASSISTANT,
        authenticate=authenticate,
    )
    message_events: list[Any] = []

    @client.on_message()
    async def reply(ctx: HandlerContext, send: HandlerSend) -> None:
        run_id = await client.begin_run(ctx.event.thread_id, triggered_by_event_id=ctx.event.id)
        try:
            async with send.message_stream(run_id=run_id) as stream:
                await stream.write("hello ")
                await stream.write("world")
        finally:
            await client.end_run(run_id)

    stream_frames: list[tuple[str, dict[str, Any]]] = []

    try:
        await client.connect()

        client.socket.on_raw_event(
            "stream.start",
            lambda data: stream_frames.append(("start", data)) or asyncio.sleep(0),  # type: ignore[arg-type,func-returns-value]
        )
        client.socket.on_raw_event(
            "stream.delta",
            lambda data: stream_frames.append(("delta", data)) or asyncio.sleep(0),  # type: ignore[arg-type,func-returns-value]
        )
        client.socket.on_raw_event(
            "stream.end",
            lambda data: stream_frames.append(("end", data)) or asyncio.sleep(0),  # type: ignore[arg-type,func-returns-value]
        )

        @client.on_message(all_events=True)
        async def collect(ctx: HandlerContext, _send: HandlerSend) -> None:
            if ctx.event.author.id == DEFAULT_ASSISTANT.id:
                message_events.append(ctx.event)

        await client.join_thread(thread_id)

        async with httpx.AsyncClient(base_url=base) as http:
            await http.post(
                f"/chat/threads/{thread_id}/messages",
                json={
                    "client_id": "c_trigger_stream",
                    "content": [{"type": "text", "text": "go"}],
                },
            )

        assert await _wait_until(lambda: len(message_events) >= 1)

        final = message_events[0]
        text = final.content[0].text
        assert text == "hello world"
    finally:
        await client.disconnect()


async def test_server_tool_handler_responds_to_client_tool_call(
    live_server: tuple[str, ChatClient],
) -> None:
    base, chat_server = live_server
    thread_id = await _seed_thread_with_member(base, DEFAULT_ASSISTANT.model_dump(mode="json"))

    @chat_server.on_tool_call("ping")  # type: ignore[attr-defined]
    async def handle_ping(ctx, send):
        yield send.tool_result(ctx.event.tool.id, result={"pong": True})

    async def authenticate() -> dict[str, Any]:
        return {"auth": {"identity_id": DEFAULT_ASSISTANT.id}}

    client = ChatClient(
        base_url=base,
        identity=DEFAULT_ASSISTANT,
        authenticate=authenticate,
    )
    results: list[Any] = []

    @client.on_tool_result(all_events=True)
    async def on_result(ctx: HandlerContext, _send: HandlerSend) -> None:
        results.append(ctx.event)

    try:
        await client.connect()
        await client.join_thread(thread_id)

        call_event = {
            "type": "tool.call",
            "tool": {"id": "call_42", "name": "ping", "arguments": {}},
        }
        await client.socket.send_event(thread_id, call_event)

        assert await _wait_until(lambda: len(results) >= 1)
        assert results[0].tool.id == "call_42"
        assert results[0].tool.result == {"pong": True}
        assert results[0].author.role == "system"
    finally:
        await client.disconnect()
