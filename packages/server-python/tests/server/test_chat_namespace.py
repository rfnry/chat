from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from rfnry_chat_protocol import Identity, Thread, UserIdentity

from rfnry_chat_server.server.auth import HandshakeData
from rfnry_chat_server.server.chat_server import ChatServer
from rfnry_chat_server.server.namespace import NamespaceViolation


class _StubStore:
    """Minimal ChatStore stub — every method raises. Used when we only
    need to check construction-time validation."""

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError(name)


async def _auth(_: HandshakeData) -> Identity:
    return UserIdentity(id="u", name="U", metadata={})


class TestChatServerNamespaceKeys:
    def test_defaults_to_none(self) -> None:
        chat_server = ChatServer(store=_StubStore(), authenticate=_auth)  # type: ignore[arg-type]
        assert chat_server.namespace_keys is None

    def test_accepts_list(self) -> None:
        chat_server = ChatServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["organization", "workspace"],
        )
        assert chat_server.namespace_keys == ["organization", "workspace"]

    def test_rejects_empty_list(self) -> None:
        with pytest.raises(NamespaceViolation, match="non-empty"):
            ChatServer(
                store=_StubStore(),  # type: ignore[arg-type]
                authenticate=_auth,
                namespace_keys=[],
            )

    def test_rejects_duplicate_keys(self) -> None:
        with pytest.raises(NamespaceViolation, match="duplicate"):
            ChatServer(
                store=_StubStore(),  # type: ignore[arg-type]
                authenticate=_auth,
                namespace_keys=["org", "org"],
            )

    def test_rejects_empty_key(self) -> None:
        with pytest.raises(NamespaceViolation, match="empty key"):
            ChatServer(
                store=_StubStore(),  # type: ignore[arg-type]
                authenticate=_auth,
                namespace_keys=["org", ""],
            )


def _thread(tenant: dict[str, str]) -> Thread:
    return Thread(
        id="th_1",
        tenant=tenant,
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestNamespaceForThread:
    def test_returns_none_when_keys_not_configured(self) -> None:
        chat_server = ChatServer(store=_StubStore(), authenticate=_auth)  # type: ignore[arg-type]
        assert chat_server.namespace_for_thread(_thread({"org": "A"})) is None

    def test_returns_path_when_keys_configured(self) -> None:
        chat_server = ChatServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org"],
        )
        assert chat_server.namespace_for_thread(_thread({"org": "A"})) == "/A"

    def test_raises_when_thread_missing_required_key(self) -> None:
        chat_server = ChatServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org"],
        )
        with pytest.raises(NamespaceViolation, match="missing required key"):
            chat_server.namespace_for_thread(_thread({}))


class TestEnforceNamespaceOnIdentity:
    def test_noop_when_keys_not_configured(self) -> None:
        chat_server = ChatServer(store=_StubStore(), authenticate=_auth)  # type: ignore[arg-type]
        chat_server.enforce_namespace_on_identity(UserIdentity(id="u", name="U", metadata={}))

    def test_passes_when_identity_has_all_keys(self) -> None:
        chat_server = ChatServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org"],
        )
        chat_server.enforce_namespace_on_identity(
            UserIdentity(
                id="u",
                name="U",
                metadata={"tenant": {"org": "A"}},
            )
        )

    def test_raises_when_identity_missing_tenant(self) -> None:
        chat_server = ChatServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org"],
        )
        with pytest.raises(NamespaceViolation, match="missing required key"):
            chat_server.enforce_namespace_on_identity(UserIdentity(id="u", name="U", metadata={}))

    def test_raises_when_identity_missing_one_of_many_keys(self) -> None:
        chat_server = ChatServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org", "ws"],
        )
        with pytest.raises(NamespaceViolation, match="missing required key: ws"):
            chat_server.enforce_namespace_on_identity(
                UserIdentity(
                    id="u",
                    name="U",
                    metadata={"tenant": {"org": "A"}},
                )
            )
