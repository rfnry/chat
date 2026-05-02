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
