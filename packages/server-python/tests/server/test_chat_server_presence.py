from rfnry_chat_server import ChatServer, InMemoryChatStore, PresenceRegistry


def test_chat_server_exposes_presence_registry():
    server = ChatServer(store=InMemoryChatStore())
    assert isinstance(server.presence, PresenceRegistry)


def test_each_chat_server_has_independent_presence_registry():
    a = ChatServer(store=InMemoryChatStore())
    b = ChatServer(store=InMemoryChatStore())
    assert a.presence is not b.presence
