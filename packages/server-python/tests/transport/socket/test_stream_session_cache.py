from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from rfnry_chat_protocol import Thread, UserIdentity

from rfnry_chat_server.transport.socket.namespace import ThreadNamespace


def _thread(thread_id: str = "th_1") -> Thread:
    return Thread(
        id=thread_id,
        tenant={},
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _CountingStore:
    def __init__(self, thread: Thread) -> None:
        self._thread = thread
        self.get_thread_call_count = 0

    async def get_thread(self, thread_id: str) -> Thread | None:
        self.get_thread_call_count += 1
        if thread_id == self._thread.id:
            return self._thread
        return None

    async def is_member(self, thread_id: str, identity_id: str) -> bool:

        return True


def _stub_server(store: _CountingStore) -> Any:

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

    box: list[dict[str, Any]] = [{"identity": identity}]

    async def get_session(s: str, namespace: str | None = None) -> dict[str, Any]:

        return dict(box[0])

    async def save_session(s: str, session: dict[str, Any], namespace: str | None = None) -> None:
        box[0] = dict(session)

    ns.get_session = get_session  # type: ignore[method-assign]
    ns.save_session = save_session  # type: ignore[method-assign]
    return box[0]


class TestStreamSessionCache:
    async def test_stream_delta_does_not_re_check_access_after_start(self) -> None:

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

        assert calls_during == 1, (
            f"expected exactly 1 get_thread call (from stream:start), "
            f"but got {calls_during} (deltas added {calls_during - 1} extra)"
        )

    async def test_stream_end_does_not_re_check_access_after_start(self) -> None:

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
        assert calls_during == 1, f"expected 1 get_thread call (start only), got {calls_during}"

    async def test_stream_delta_bogus_event_id_returns_not_found(self) -> None:

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

        first_end = await ns.on_stream_end(
            "sid_1",
            {"event_id": "evt_z", "thread_id": "th_1"},
        )
        assert "error" not in first_end

        second_end = await ns.on_stream_end(
            "sid_1",
            {"event_id": "evt_z", "thread_id": "th_1"},
        )
        assert second_end.get("error", {}).get("code") == "not_found"

    async def test_stream_delta_malformed_returns_invalid_request_not_not_found(self) -> None:

        alice = UserIdentity(id="u_alice", name="Alice", metadata={})
        thread = _thread("th_1")
        store = _CountingStore(thread)
        server = _stub_server(store)
        ns = _make_ns(server)
        _setup_session(ns, "sid_1", alice)

        result = await ns.on_stream_delta(
            "sid_1",
            {
                "event_id": "evt_x",
                "text": "hello",
            },
        )
        assert result.get("error", {}).get("code") == "invalid_request"
