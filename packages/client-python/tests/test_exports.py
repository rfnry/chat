import rfnry_chat_client


def test_public_exports() -> None:
    expected = {
        "ChatClient",
        "ChatAuthError",
        "ChatHttpError",
        "HandlerDispatcher",
        "HandlerCallable",
        "HandlerContext",
        "HandlerSend",
        "RestTransport",
        "SocketTransport",
        "SocketTransportError",
        "ThreadConflictError",
        "ThreadNotFoundError",
    }
    assert expected.issubset(set(dir(rfnry_chat_client)))


def test_every_all_symbol_is_importable() -> None:
    for name in rfnry_chat_client.__all__:
        assert hasattr(rfnry_chat_client, name), f"missing: {name}"
