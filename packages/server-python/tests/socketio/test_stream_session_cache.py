"""Regression tests for T7: stream hot-path session cache.

Server: on_stream_start must stash the authorized thread in the session so
that on_stream_delta and on_stream_end can skip _access_check entirely.
The store.get_thread call count across start + N deltas must be exactly 1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from rfnry_chat_protocol import Thread, UserIdentity

from rfnry_chat_server.socketio.server import ThreadNamespace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _thread(thread_id: str = "th_1") -> Thread:
    return Thread(
        id=thread_id,
        tenant={},
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _CountingStore:
    """Thin wrapper around a dict-of-threads that counts get_thread calls."""

    def __init__(self, thread: Thread) -> None:
        self._thread = thread
        self.get_thread_call_count = 0

    async def get_thread(self, thread_id: str) -> Thread | None:
        self.get_thread_call_count += 1
        if thread_id == self._thread.id:
            return self._thread
        return None

    async def is_member(self, thread_id: str, identity_id: str) -> bool:
        # Always allow — we only want to test access-check short-circuit, not policy.
        return True


def _stub_server(store: _CountingStore) -> Any:
    """Return a MagicMock ChatServer wired to the counting store."""
    server = MagicMock()
    server.namespace_keys = None
    server.store = store
    server.check_authorize = AsyncMock(return_value=True)
    server.broadcast_stream_start = AsyncMock()
    server.broadcast_stream_delta = AsyncMock()
    server.broadcast_stream_end = AsyncMock()
    return server


def _make_ns(server: Any) -> ThreadNamespace:
    ns = ThreadNamespace("/", server=server, replay_cap=100)
    return ns


def _setup_session(ns: ThreadNamespace, sid: str, identity: Any) -> dict[str, Any]:
    """Seed an in-process session dict; override get_session / save_session.

    Returns a container whose single ``"data"`` key always points at the
    current session payload so callers can inspect the live state.
    """
    # Use a mutable container so the closure can replace the session dict.
    # We can't do `store = new_value` in Python closures, so we box it.
    box: list[dict[str, Any]] = [{"identity": identity}]

    async def get_session(s: str, namespace: str | None = None) -> dict[str, Any]:
        # Return a copy so that mutating the result doesn't affect the stored
        # session until save_session is explicitly called.
        return dict(box[0])

    async def save_session(s: str, session: dict[str, Any], namespace: str | None = None) -> None:
        box[0] = dict(session)

    ns.get_session = get_session  # type: ignore[method-assign]
    ns.save_session = save_session  # type: ignore[method-assign]
    return box[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStreamSessionCache:
    """stream:delta and stream:end must NOT call store.get_thread after
    on_stream_start has cached the authorized thread in the session."""

    async def test_stream_delta_does_not_re_check_access_after_start(self) -> None:
        """Core regression test: 20 deltas after a start must NOT add any
        extra get_thread calls beyond the single call from on_stream_start."""
        alice = UserIdentity(id="u_alice", name="Alice", metadata={})
        thread = _thread("th_1")
        store = _CountingStore(thread)
        server = _stub_server(store)
        ns = _make_ns(server)
        _setup_session(ns, "sid_1", alice)

        calls_before = store.get_thread_call_count

        start_result = await ns.on_stream_start(
            "sid_1",
            {
                "event_id": "evt_x",
                "thread_id": "th_1",
                "run_id": "run_1",
                "target_type": "message",
                "author": {
                    "role": "user",
                    "id": "u_alice",
                    "name": "Alice",
                    "metadata": {},
                },
            },
        )
        assert "error" not in start_result, f"stream:start failed: {start_result}"

        for i in range(20):
            delta_result = await ns.on_stream_delta(
                "sid_1",
                {
                    "event_id": "evt_x",
                    "thread_id": "th_1",
                    "text": f"token_{i}",
                },
            )
            assert "error" not in delta_result, f"delta {i} failed: {delta_result}"

        calls_during = store.get_thread_call_count - calls_before
        # on_stream_start does ONE access_check (1 get_thread call).
        # The 20 deltas must NOT add any more.
        assert calls_during == 1, (
            f"expected exactly 1 get_thread call (from stream:start), "
            f"but got {calls_during} (deltas added {calls_during - 1} extra)"
        )

    async def test_stream_end_does_not_re_check_access_after_start(self) -> None:
        """stream:end must also skip _access_check after on_stream_start cached the thread."""
        alice = UserIdentity(id="u_alice", name="Alice", metadata={})
        thread = _thread("th_1")
        store = _CountingStore(thread)
        server = _stub_server(store)
        ns = _make_ns(server)
        _setup_session(ns, "sid_1", alice)

        calls_before = store.get_thread_call_count

        await ns.on_stream_start(
            "sid_1",
            {
                "event_id": "evt_y",
                "thread_id": "th_1",
                "run_id": "run_1",
                "target_type": "message",
                "author": {
                    "role": "user",
                    "id": "u_alice",
                    "name": "Alice",
                    "metadata": {},
                },
            },
        )

        end_result = await ns.on_stream_end(
            "sid_1",
            {
                "event_id": "evt_y",
                "thread_id": "th_1",
            },
        )
        assert "error" not in end_result, f"stream:end failed: {end_result}"

        calls_during = store.get_thread_call_count - calls_before
        assert calls_during == 1, (
            f"expected 1 get_thread call (start only), got {calls_during}"
        )

    async def test_stream_delta_bogus_event_id_returns_not_found(self) -> None:
        """stream:delta with an event_id that was never started must return not_found."""
        alice = UserIdentity(id="u_alice", name="Alice", metadata={})
        thread = _thread("th_1")
        store = _CountingStore(thread)
        server = _stub_server(store)
        ns = _make_ns(server)
        _setup_session(ns, "sid_1", alice)

        result = await ns.on_stream_delta(
            "sid_1",
            {
                "event_id": "evt_never_started",
                "thread_id": "th_1",
                "text": "oops",
            },
        )
        assert result.get("error", {}).get("code") == "not_found"

    async def test_stream_end_bogus_event_id_returns_not_found(self) -> None:
        """stream:end with an event_id that was never started must return not_found."""
        alice = UserIdentity(id="u_alice", name="Alice", metadata={})
        thread = _thread("th_1")
        store = _CountingStore(thread)
        server = _stub_server(store)
        ns = _make_ns(server)
        _setup_session(ns, "sid_1", alice)

        result = await ns.on_stream_end(
            "sid_1",
            {
                "event_id": "evt_never_started",
                "thread_id": "th_1",
            },
        )
        assert result.get("error", {}).get("code") == "not_found"

    async def test_stream_end_pops_event_from_session(self) -> None:
        """After stream:end the event_id must be removed from the session so a
        second stream:end for the same event_id returns not_found."""
        alice = UserIdentity(id="u_alice", name="Alice", metadata={})
        thread = _thread("th_1")
        store = _CountingStore(thread)
        server = _stub_server(store)
        ns = _make_ns(server)
        _setup_session(ns, "sid_1", alice)

        await ns.on_stream_start(
            "sid_1",
            {
                "event_id": "evt_z",
                "thread_id": "th_1",
                "run_id": "run_1",
                "target_type": "message",
                "author": {
                    "role": "user",
                    "id": "u_alice",
                    "name": "Alice",
                    "metadata": {},
                },
            },
        )

        # First end: ok
        first_end = await ns.on_stream_end(
            "sid_1",
            {"event_id": "evt_z", "thread_id": "th_1"},
        )
        assert "error" not in first_end

        # Second end: must be not_found (event was popped)
        second_end = await ns.on_stream_end(
            "sid_1",
            {"event_id": "evt_z", "thread_id": "th_1"},
        )
        assert second_end.get("error", {}).get("code") == "not_found"

    async def test_stream_delta_malformed_returns_invalid_request_not_not_found(self) -> None:
        """Frame validation must happen BEFORE session lookup.
        A malformed frame (missing required field) should return invalid_request,
        not not_found, even though there is no active stream for that event_id."""
        alice = UserIdentity(id="u_alice", name="Alice", metadata={})
        thread = _thread("th_1")
        store = _CountingStore(thread)
        server = _stub_server(store)
        ns = _make_ns(server)
        _setup_session(ns, "sid_1", alice)

        # Missing thread_id — should fail validation before session lookup
        result = await ns.on_stream_delta(
            "sid_1",
            {
                # thread_id deliberately omitted to trigger invalid_request
                "event_id": "evt_x",
                "text": "hello",
            },
        )
        assert result.get("error", {}).get("code") == "invalid_request"
