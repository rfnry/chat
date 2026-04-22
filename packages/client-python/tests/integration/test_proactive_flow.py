from __future__ import annotations

import asyncio
from typing import Any

import pytest
from rfnry_chat_protocol import (
    AssistantIdentity,
    MessageEvent,
    TextPart,
    ThreadInvitedFrame,
    UserIdentity,
)

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.handler.send import HandlerSend

# The live_server fixture's auth reads identity_id from the Socket.IO
# handshake `auth` payload or — for REST — from the `x-identity-id` header.
# Map identity_id == "a_helper" to the assistant, anything else to the user
# "u_alice". Use those IDs so both clients authenticate to distinct
# identities on both transports.
ALICE = UserIdentity(id="u_alice", name="Alice")
BOT = AssistantIdentity(id="a_helper", name="Helper")


def _authenticate_as(identity_id: str) -> Any:
    async def _authenticate() -> dict[str, Any]:
        return {
            "auth": {"identity_id": identity_id},
            "headers": {"x-identity-id": identity_id},
        }

    return _authenticate


async def test_bot_open_thread_with_triggers_on_invited_and_delivers_message(
    live_server: tuple[str, Any],
) -> None:
    """Bot calls open_thread_with(user=alice, message=...).

    Asserts:
      - Alice's on_invited handler fires exactly once with the right frame.
      - After auto-join, Alice receives the bot's message via on_message.
    """
    base, _chat_server = live_server

    alice = ChatClient(
        base_url=base, identity=ALICE, authenticate=_authenticate_as(ALICE.id)
    )
    bot = ChatClient(
        base_url=base, identity=BOT, authenticate=_authenticate_as(BOT.id)
    )

    invited_received: list[ThreadInvitedFrame] = []
    invited_event = asyncio.Event()
    message_received: list[MessageEvent] = []
    message_event = asyncio.Event()

    @alice.on_invited()
    async def on_inv(frame: ThreadInvitedFrame) -> None:
        invited_received.append(frame)
        invited_event.set()

    @alice.on_message()
    async def on_msg(ctx: HandlerContext, _send: HandlerSend) -> None:
        if isinstance(ctx.event, MessageEvent) and ctx.event.author.id == BOT.id:
            message_received.append(ctx.event)
            message_event.set()

    await alice.connect()
    await bot.connect()

    try:
        thread, _sent_event = await bot.open_thread_with(
            message=[TextPart(text="ping from bot")],
            user=ALICE,
        )

        # Wait for the inbox frame.
        await asyncio.wait_for(invited_event.wait(), timeout=5)
        assert len(invited_received) == 1
        frame = invited_received[0]
        assert frame.thread.id == thread.id
        assert frame.added_member.id == ALICE.id
        assert frame.added_by.id == BOT.id

        # Alice auto-joined (default behavior). Wait for the bot's message.
        await asyncio.wait_for(message_event.wait(), timeout=5)
        assert len(message_received) == 1
        msg = message_received[0]
        assert msg.thread_id == thread.id
        assert any(
            getattr(p, "type", None) == "text"
            and getattr(p, "text", None) == "ping from bot"
            for p in msg.content
        )
    finally:
        await alice.disconnect()
        await bot.disconnect()


pytestmark = pytest.mark.asyncio
