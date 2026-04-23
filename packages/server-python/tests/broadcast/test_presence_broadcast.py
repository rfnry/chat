from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rfnry_chat_protocol import PresenceJoinedFrame, PresenceLeftFrame, UserIdentity

from rfnry_chat_server.broadcast.recording import RecordingBroadcaster


@pytest.mark.asyncio
async def test_records_presence_joined() -> None:
    bc = RecordingBroadcaster()
    frame = PresenceJoinedFrame(
        identity=UserIdentity(id="u_a", name="Alice", metadata={}),
        at=datetime(2026, 4, 23, tzinfo=UTC),
    )
    await bc.broadcast_presence_joined(frame, tenant_path="/", namespace="/")
    assert bc.presence_joined == [frame]
    assert bc.presence_joined_with_kwargs == [(frame, "/", None, "/")]


@pytest.mark.asyncio
async def test_records_presence_joined_with_skip_sid() -> None:
    bc = RecordingBroadcaster()
    frame = PresenceJoinedFrame(
        identity=UserIdentity(id="u_a", name="Alice", metadata={}),
        at=datetime(2026, 4, 23, tzinfo=UTC),
    )
    await bc.broadcast_presence_joined(frame, tenant_path="/", namespace="/", skip_sid="sid_joining")
    assert bc.presence_joined_with_kwargs == [(frame, "/", "sid_joining", "/")]


@pytest.mark.asyncio
async def test_records_presence_left() -> None:
    bc = RecordingBroadcaster()
    frame = PresenceLeftFrame(
        identity=UserIdentity(id="u_a", name="Alice", metadata={}),
        at=datetime(2026, 4, 23, tzinfo=UTC),
    )
    await bc.broadcast_presence_left(frame, tenant_path="/", namespace="/")
    assert bc.presence_left == [frame]
    assert bc.presence_left_with_kwargs == [(frame, "/", "/")]
