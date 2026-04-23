from rfnry_chat_server import ChatServer, InMemoryChatStore, PresenceRegistry


def test_chat_server_exposes_presence_registry():
    server = ChatServer(store=InMemoryChatStore())
    assert isinstance(server.presence, PresenceRegistry)
