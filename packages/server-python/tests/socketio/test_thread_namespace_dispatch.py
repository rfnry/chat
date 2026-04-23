"""Unit tests pinning python-socketio's wildcard namespace calling convention.

The namespace_keys defense-in-depth feature relies on an undocumented
internal of python-socketio 5.13+: when a namespace handler is registered
under the wildcard `"*"`, `AsyncServer._get_namespace_handler` prepends the
concrete namespace as the first positional argument to every `trigger_event`
call. `ThreadNamespace.trigger_event` pops that arg and caches it per-sid so
handlers can look up their concrete namespace via `_concrete_namespace_for`.

The upper pin `python-socketio<6` in pyproject.toml protects the major-bump
blast radius, but these tests surface any minor-version behavior drift
immediately and close to the root cause, rather than as a confusing
"ConnectionRefusedError: namespace_invalid" deep inside an integration
test. If upstream ever changes the calling convention, the failure message
from these tests will name exactly what changed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rfnry_chat_protocol import UserIdentity

from rfnry_chat_server.socketio.server import ThreadNamespace


def _stub_server(namespace_keys: list[str] | None = None) -> Any:
    """Return a MagicMock that satisfies the attributes ThreadNamespace reads."""
    server = MagicMock()
    server.namespace_keys = namespace_keys
    return server


class TestTriggerEventWildcardDispatch:
    """In wildcard mode, python-socketio prepends the concrete namespace as
    args[0]. ThreadNamespace.trigger_event must pop it and cache it per-sid."""

    async def test_wildcard_caches_concrete_namespace_and_pops_arg(self) -> None:
        ns = ThreadNamespace("*", server=_stub_server(["org"]), replay_cap=100)
        captured: dict[str, Any] = {}

        async def fake_on_connect(sid: str, environ: dict[str, Any], auth: Any) -> None:
            captured["sid"] = sid
            captured["environ"] = environ
            captured["auth"] = auth

        ns.on_connect = fake_on_connect  # type: ignore[method-assign]

        await ns.trigger_event(
            "connect",
            "/A",  # concrete namespace (prepended by python-socketio)
            "sid_abc",  # sid (handler's first real positional)
            {"HTTP_AUTHORIZATION": "Bearer x"},
            {"token": "y"},
        )

        # Cache was populated with the concrete namespace, keyed by sid.
        assert ns._sid_namespaces == {"sid_abc": "/A"}
        # The handler received args WITHOUT the concrete namespace prefix.
        assert captured == {
            "sid": "sid_abc",
            "environ": {"HTTP_AUTHORIZATION": "Bearer x"},
            "auth": {"token": "y"},
        }

    async def test_wildcard_dispatch_propagates_return_value(self) -> None:
        ns = ThreadNamespace("*", server=_stub_server(["org"]), replay_cap=100)

        async def fake_on_thread_join(sid: str, data: dict[str, Any]) -> dict[str, Any]:
            return {"thread_id": data["thread_id"], "replayed": [], "replay_truncated": False}

        ns.on_thread_join = fake_on_thread_join  # type: ignore[method-assign]
        # Seed the cache as `connect` would have.
        ns._sid_namespaces["sid_abc"] = "/A"

        result = await ns.trigger_event(
            "thread:join",
            "/A",
            "sid_abc",
            {"thread_id": "th_1"},
        )
        assert result == {
            "thread_id": "th_1",
            "replayed": [],
            "replay_truncated": False,
        }

    async def test_concrete_namespace_for_returns_cached_value(self) -> None:
        ns = ThreadNamespace("*", server=_stub_server(["org"]), replay_cap=100)
        ns._sid_namespaces["sid_abc"] = "/A/X"
        assert ns._concrete_namespace_for("sid_abc") == "/A/X"

    async def test_concrete_namespace_for_raises_when_missing(self) -> None:
        ns = ThreadNamespace("*", server=_stub_server(["org"]), replay_cap=100)
        with pytest.raises(RuntimeError, match="no concrete namespace cached"):
            ns._concrete_namespace_for("sid_unknown")


class TestTriggerEventStaticDispatch:
    """In static mode (registered under `/`), python-socketio does NOT prepend
    the concrete namespace. ThreadNamespace.trigger_event must leave args alone
    and `_concrete_namespace_for` must read from `self.namespace` directly."""

    async def test_static_does_not_consume_namespace_arg(self) -> None:
        ns = ThreadNamespace("/", server=_stub_server(None), replay_cap=100)
        captured: dict[str, Any] = {}

        async def fake_on_connect(sid: str, environ: dict[str, Any], auth: Any) -> None:
            captured["sid"] = sid
            captured["environ"] = environ
            captured["auth"] = auth

        ns.on_connect = fake_on_connect  # type: ignore[method-assign]

        await ns.trigger_event(
            "connect",
            "sid_abc",
            {"HTTP_AUTHORIZATION": "Bearer x"},
            {"token": "y"},
        )

        assert ns._sid_namespaces == {}
        assert captured == {
            "sid": "sid_abc",
            "environ": {"HTTP_AUTHORIZATION": "Bearer x"},
            "auth": {"token": "y"},
        }

    async def test_static_concrete_namespace_for_returns_self_namespace(self) -> None:
        ns = ThreadNamespace("/", server=_stub_server(None), replay_cap=100)
        assert ns._concrete_namespace_for("any_sid") == "/"


class TestTriggerEventEventNameTranslation:
    """Socket.IO event names use colons (`thread:join`) but class-based
    `AsyncNamespace` handler methods use underscores (`on_thread_join`).
    `trigger_event` translates between them so the class-based pattern
    picks up the colon-separated events."""

    async def test_colon_event_maps_to_underscore_method(self) -> None:
        ns = ThreadNamespace("/", server=_stub_server(None), replay_cap=100)
        calls: list[tuple[str, Any]] = []

        async def fake_on_thread_join(sid: str, data: dict[str, Any]) -> None:
            calls.append(("thread_join", (sid, data)))

        async def fake_on_message_send(sid: str, data: dict[str, Any]) -> None:
            calls.append(("message_send", (sid, data)))

        ns.on_thread_join = fake_on_thread_join  # type: ignore[method-assign]
        ns.on_message_send = fake_on_message_send  # type: ignore[method-assign]

        await ns.trigger_event("thread:join", "sid_1", {"thread_id": "th_1"})
        await ns.trigger_event("message:send", "sid_1", {"thread_id": "th_1", "draft": {}})

        assert [c[0] for c in calls] == ["thread_join", "message_send"]

    async def test_unknown_event_returns_none(self) -> None:
        ns = ThreadNamespace("/", server=_stub_server(None), replay_cap=100)
        # No handler defined for "mystery:event" — trigger_event returns None.
        result = await ns.trigger_event("mystery:event", "sid_1", {})
        assert result is None


class TestTriggerEventDisconnectReasonFallback:
    """python-socketio 5.12+ passes an extra `reason` arg to disconnect
    handlers. ThreadNamespace.on_disconnect is a 1-arg method, so trigger_event
    has a TypeError fallback that retries with `args[:-1]`."""

    async def test_disconnect_accepts_legacy_one_arg_shape(self) -> None:
        ns = ThreadNamespace("/", server=_stub_server(None), replay_cap=100)
        calls: list[str] = []

        async def fake_on_disconnect(sid: str) -> None:
            calls.append(sid)

        ns.on_disconnect = fake_on_disconnect  # type: ignore[method-assign]

        # Simulate a 5.12+ dispatch with the extra `reason` arg.
        await ns.trigger_event("disconnect", "sid_1", "transport closed")

        assert calls == ["sid_1"]

    async def test_disconnect_cleans_sid_namespace_cache(self) -> None:
        ns = ThreadNamespace("*", server=_stub_server(["org"]), replay_cap=100)
        ns._sid_namespaces["sid_1"] = "/A"

        async def fake_on_disconnect(sid: str) -> None:
            return None

        ns.on_disconnect = fake_on_disconnect  # type: ignore[method-assign]

        # Wildcard mode: trigger_event prepends the concrete namespace.
        await ns.trigger_event("disconnect", "/A", "sid_1", "transport closed")

        assert "sid_1" not in ns._sid_namespaces


class TestOnConnectAutoJoinsInboxRoom:
    """After `on_connect` resolves the identity and saves the session, the sid
    must be auto-joined to a namespace-scoped `inbox:<identity_id>` room so
    Task 4's `broadcast_thread_invited` reaches exactly that sid."""

    async def test_on_connect_auto_joins_identity_inbox_room(self) -> None:
        # Static-namespace path: no namespace_keys, no wildcard.
        alice = UserIdentity(id="u_alice", name="Alice", metadata={})

        server = MagicMock()
        server.namespace_keys = None
        server.authenticate = AsyncMock(return_value=alice)
        # Presence registry stub: `add` is awaited on every connect; returning
        # False skips the broadcast so we don't need a broadcaster stub here.
        server.presence.add = AsyncMock(return_value=False)
        server.broadcaster = None

        ns = ThreadNamespace("/", server=server, replay_cap=100)

        # Capture side effects without touching a real socketio.Server.
        entered: list[tuple[str, str]] = []

        async def fake_enter_room(sid: str, room: str, namespace: str | None = None) -> None:
            entered.append((sid, room))

        saved: list[dict[str, Any]] = []

        async def fake_save_session(sid: str, session: dict[str, Any], namespace: str | None = None) -> None:
            saved.append(session)

        ns.enter_room = fake_enter_room  # type: ignore[method-assign]
        ns.save_session = fake_save_session  # type: ignore[method-assign]

        await ns.on_connect("sid_test", environ={}, auth={"identity_id": "u_alice"})

        assert ("sid_test", "inbox:u_alice") in entered
        assert len(saved) == 1
        assert saved[0]["identity"] is alice

    async def test_on_connect_auto_joins_identity_inbox_room_wildcard(self) -> None:
        # Wildcard path: namespace_keys=["org"] and a concrete namespace "/acme".
        # The identity must carry tenant={"org": "acme"} to pass namespace match.
        alice = UserIdentity(
            id="u_alice",
            name="Alice",
            metadata={"tenant": {"org": "acme"}},
        )

        server = MagicMock()
        server.namespace_keys = ["org"]
        server.authenticate = AsyncMock(return_value=alice)
        server.presence.add = AsyncMock(return_value=False)
        server.broadcaster = None

        ns = ThreadNamespace("*", server=server, replay_cap=100)

        entered: list[tuple[str, str]] = []

        async def fake_enter_room(sid: str, room: str, namespace: str | None = None) -> None:
            entered.append((sid, room))

        saved: list[dict[str, Any]] = []

        async def fake_save_session(sid: str, session: dict[str, Any], namespace: str | None = None) -> None:
            saved.append(session)

        ns.enter_room = fake_enter_room  # type: ignore[method-assign]
        ns.save_session = fake_save_session  # type: ignore[method-assign]

        # Route through trigger_event with the concrete namespace prepended,
        # mirroring what python-socketio does under wildcard registration.
        await ns.trigger_event(
            "connect",
            "/acme",  # concrete namespace (prepended by python-socketio)
            "sid_x",  # sid
            {},  # environ
            {"identity_id": "u_alice"},  # auth
        )

        assert ("sid_x", "inbox:u_alice") in entered
        assert len(saved) == 1
        assert saved[0]["identity"] is alice
        assert saved[0]["namespace"] == "/acme"
        assert saved[0]["namespace_tenant"] == {"org": "acme"}
