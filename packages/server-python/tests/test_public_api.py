import rfnry_chat_server


def test_every_all_symbol_is_importable() -> None:
    for name in rfnry_chat_server.__all__:
        assert hasattr(rfnry_chat_server, name), f"missing: {name}"
