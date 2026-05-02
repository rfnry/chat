from datetime import UTC, datetime

from rfnry_chat_protocol import Thread
from rfnry_chat_protocol.tenant import TenantScope

from rfnry_chat_server.observability import NullSink, Observability
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.memory import InMemoryChatStore


def test_chat_server_default_observability_attached() -> None:
    server = ChatServer(store=InMemoryChatStore())
    assert isinstance(server.observability, Observability)


def test_chat_server_custom_observability_attached() -> None:
    obs = Observability(sink=NullSink())
    server = ChatServer(store=InMemoryChatStore(), observability=obs)
    assert server.observability is obs


def _thread(tenant: TenantScope) -> Thread:
    return Thread(
        id="thr_x",
        tenant=tenant,
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_scope_leaf_for_thread_default_when_no_namespace_keys() -> None:
    server = ChatServer(store=InMemoryChatStore())
    thread = _thread({"org": "acme"})
    assert server.scope_leaf_for_thread(thread) == "default"


def test_scope_leaf_for_thread_uses_namespace_keys() -> None:
    server = ChatServer(store=InMemoryChatStore(), namespace_keys=["org", "team"])
    thread = _thread({"org": "acme", "team": "core"})
    assert server.scope_leaf_for_thread(thread) == "acme/core"
