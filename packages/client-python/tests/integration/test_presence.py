from __future__ import annotations

import asyncio
from typing import Any

import pytest
from rfnry_chat_protocol import (
    AssistantIdentity,
    PresenceJoinedFrame,
    PresenceLeftFrame,
    UserIdentity,
)

from rfnry_chat_client.client import ChatClient

BOT = AssistantIdentity(id="a_helper", name="Helper")
ALICE = UserIdentity(id="u_alice", name="Alice")


def _authenticate_as(identity_id: str) -> Any:
    async def _authenticate() -> dict[str, Any]:
        return {
            "auth": {"identity_id": identity_id},
            "headers": {"x-identity-id": identity_id},
        }

    return _authenticate


async def test_presence_round_trip_live(live_server: tuple[str, Any]) -> None:

    base, _ = live_server

    observer = ChatClient(
        base_url=base,
        identity=ALICE,
        authenticate=_authenticate_as(ALICE.id),
    )
    received_joined: list[PresenceJoinedFrame] = []
    received_left: list[PresenceLeftFrame] = []
    joined_seen = asyncio.Event()
    left_seen = asyncio.Event()

    @observer.on_presence_joined()
    async def _on_joined(frame: PresenceJoinedFrame) -> None:
        if frame.identity.id == BOT.id:
            received_joined.append(frame)
            joined_seen.set()

    @observer.on_presence_left()
    async def _on_left(frame: PresenceLeftFrame) -> None:
        if frame.identity.id == BOT.id:
            received_left.append(frame)
            left_seen.set()

    await observer.connect()
    try:
        agent = ChatClient(
            base_url=base,
            identity=BOT,
            authenticate=_authenticate_as(BOT.id),
        )
        await agent.connect()
        try:
            await asyncio.wait_for(joined_seen.wait(), timeout=5.0)
            assert received_joined[0].identity.id == BOT.id

            snapshot = await observer.rest.list_presence()
            ids = {m.id for m in snapshot.members}
            assert BOT.id in ids
            assert ALICE.id not in ids
        finally:
            await agent.disconnect()

        await asyncio.wait_for(left_seen.wait(), timeout=5.0)
        assert received_left[0].identity.id == BOT.id
    finally:
        await observer.disconnect()


pytestmark = pytest.mark.asyncio
