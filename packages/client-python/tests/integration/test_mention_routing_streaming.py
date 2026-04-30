from __future__ import annotations

import asyncio
from typing import Any

import httpx
from rfnry_chat_protocol import AssistantIdentity, UserIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.send import Send
from rfnry_chat_client.stream import Stream

ALICE = UserIdentity(id="u_alice", name="Alice")
HELPER = AssistantIdentity(id="a_helper", name="Helper")


async def _seed(base: str, members: list[dict[str, Any]]) -> str:
    async with httpx.AsyncClient(base_url=base) as http:
        create = await http.post("/chat/threads", json={"tenant": {}})
        thread_id = create.json()["id"]
        for ident in members:
            await http.post(
                f"/chat/threads/{thread_id}/members",
                json={"identity": ident},
            )
    return thread_id


async def _wait_until(predicate: Any, attempts: int = 80, delay: float = 0.05) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await asyncio.sleep(delay)
    return predicate()


async def test_streamed_message_recipients_from_sender_preserved(
    live_server: tuple[str, Any],
) -> None:

    base, _ = live_server
    coordinator = AssistantIdentity(id="coordinator", name="Coordinator")
    thread_id = await _seed(
        base,
        [HELPER.model_dump(mode="json"), coordinator.model_dump(mode="json")],
    )

    async def auth_helper() -> dict[str, Any]:
        return {"auth": {"identity_id": HELPER.id}}

    helper_client = ChatClient(base_url=base, identity=HELPER, authenticate=auth_helper)

    async def auth_alice() -> dict[str, Any]:
        return {"auth": {"identity_id": ALICE.id}}

    alice_client = ChatClient(base_url=base, identity=ALICE, authenticate=auth_alice)
    received: list[Any] = []

    @alice_client.on("message", all_events=True)
    async def observe(ctx: HandlerContext, _send: Send) -> None:
        received.append(ctx.event)

    try:
        await helper_client.connect()
        await alice_client.connect()
        await alice_client.join_thread(thread_id)

        run_id = await helper_client.begin_run(thread_id)
        stream = Stream(
            client=helper_client,
            thread_id=thread_id,
            run_id=run_id,
            author=HELPER,
            target_type="message",
            recipients=["coordinator"],
        )
        async with stream as s:
            await s.write("@u_alice please look")
        await helper_client.end_run(run_id)

        assert await _wait_until(lambda: any(e.type == "message" for e in received))
        msg = next(e for e in received if e.type == "message")

        assert msg.recipients == ["coordinator"]
        assert msg.content[0].text == "@u_alice please look"
    finally:
        await alice_client.disconnect()
        await helper_client.disconnect()


async def test_streamed_message_no_recipients_parses_from_prose(
    live_server: tuple[str, Any],
) -> None:

    base, _ = live_server
    thread_id = await _seed(
        base,
        [HELPER.model_dump(mode="json")],
    )

    async def auth_helper() -> dict[str, Any]:
        return {"auth": {"identity_id": HELPER.id}}

    helper_client = ChatClient(base_url=base, identity=HELPER, authenticate=auth_helper)

    async def auth_alice() -> dict[str, Any]:
        return {"auth": {"identity_id": ALICE.id}}

    alice_client = ChatClient(base_url=base, identity=ALICE, authenticate=auth_alice)
    received: list[Any] = []

    @alice_client.on("message", all_events=True)
    async def observe(ctx: HandlerContext, _send: Send) -> None:
        received.append(ctx.event)

    try:
        await helper_client.connect()
        await alice_client.connect()
        await alice_client.join_thread(thread_id)

        run_id = await helper_client.begin_run(thread_id)
        stream = Stream(
            client=helper_client,
            thread_id=thread_id,
            run_id=run_id,
            author=HELPER,
            target_type="message",
        )
        async with stream as s:
            await s.write("@u_alice ")
            await s.write("hello")
        await helper_client.end_run(run_id)

        assert await _wait_until(lambda: any(e.type == "message" for e in received))
        msg = next(e for e in received if e.type == "message")
        assert msg.recipients == ["u_alice"]
        assert msg.content[0].text == "@u_alice hello"
    finally:
        await alice_client.disconnect()
        await helper_client.disconnect()
