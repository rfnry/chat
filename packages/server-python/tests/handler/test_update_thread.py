from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from rfnry_chat_server.analytics.collector import AssistantAnalytics
from rfnry_chat_server.handler.context import HandlerContext
from rfnry_chat_server.protocol.event import Event
from rfnry_chat_server.protocol.identity import AssistantIdentity, UserIdentity
from rfnry_chat_server.protocol.run import Run
from rfnry_chat_server.protocol.thread import Thread, ThreadPatch
from rfnry_chat_server.store.protocol import ChatStore
from rfnry_chat_server.store.types import Page


class _FakeStore:
    async def list_events(
        self,
        thread_id: str,
        since: Any = None,
        until: Any = None,
        limit: int = 100,
        types: Any = None,
    ) -> Page[Event]:
        return Page[Event](items=[], next_cursor=None)


def _make_thread(**overrides: Any) -> Thread:
    base: dict[str, Any] = dict(
        id="t_test",
        tenant={"location": "warehouse_a"},
        metadata={"visibility": "private"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Thread(**base)


def _build_ctx(thread: Thread, update_thread: Any = None) -> HandlerContext:
    store = cast(ChatStore, _FakeStore())
    assistant = AssistantIdentity(id="ops-assistant", name="Ops Assistant", metadata={})
    run = Run(
        id="r_1",
        thread_id=thread.id,
        assistant=assistant,
        triggered_by=UserIdentity(id="u_alice", name="Alice", metadata={}),
        status="running",
        started_at=datetime.now(UTC),
    )
    analytics = AssistantAnalytics(
        on_analytics=None,
        thread_id=thread.id,
        run_id="r_1",
        assistant_id=assistant.id,
    )
    return HandlerContext(
        store=store,
        thread=thread,
        run=run,
        assistant=assistant,
        analytics=analytics,
        update_thread=update_thread,
    )


async def test_update_thread_raises_without_callable() -> None:
    ctx = _build_ctx(_make_thread())  # no update_thread passed
    with pytest.raises(RuntimeError, match="update_thread is not available"):
        await ctx.update_thread(ThreadPatch(metadata={"visibility": "public"}))


async def test_update_thread_delegates_to_callable_and_refreshes_ctx_thread() -> None:
    thread = _make_thread()
    received: dict[str, Any] = {}

    async def fake_update(current: Thread, patch: ThreadPatch) -> Thread:
        received["current"] = current
        received["patch"] = patch
        # Return an updated thread reflecting the patch.
        new_metadata = {**(current.metadata or {}), **(patch.metadata or {})}
        return Thread(
            id=current.id,
            tenant=patch.tenant or current.tenant,
            metadata=new_metadata,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )

    ctx = _build_ctx(thread, update_thread=fake_update)
    returned = await ctx.update_thread(ThreadPatch(metadata={"visibility": "public"}))

    # Returned thread has the patched metadata
    assert returned.metadata["visibility"] == "public"
    # ctx.thread is refreshed in place so subsequent reads see the new state
    assert ctx.thread.metadata["visibility"] == "public"
    # The callable received the thread that was current at call time
    assert received["current"].id == "t_test"
    assert received["patch"].metadata == {"visibility": "public"}


async def test_update_thread_multiple_calls_see_latest_state() -> None:
    thread = _make_thread(metadata={"step": 0})
    captured_currents: list[Thread] = []

    async def fake_update(current: Thread, patch: ThreadPatch) -> Thread:
        captured_currents.append(current)
        new_metadata = {**(current.metadata or {}), **(patch.metadata or {})}
        return Thread(
            id=current.id,
            tenant=patch.tenant or current.tenant,
            metadata=new_metadata,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )

    ctx = _build_ctx(thread, update_thread=fake_update)
    await ctx.update_thread(ThreadPatch(metadata={"step": 1}))
    await ctx.update_thread(ThreadPatch(metadata={"step": 2}))

    # Second call sees the state the first call produced, not the original
    assert captured_currents[0].metadata == {"step": 0}
    assert captured_currents[1].metadata == {"step": 1}
    # Final ctx.thread reflects the latest update
    assert ctx.thread.metadata == {"step": 2}
