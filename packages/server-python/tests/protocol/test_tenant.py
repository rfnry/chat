from rfnry_chat_server.protocol.tenant import matches


def test_subset_match_exact() -> None:
    assert matches({"org": "A", "ws": "X"}, {"org": "A", "ws": "X"})


def test_subset_match_identity_extra_keys() -> None:
    assert matches({"org": "A"}, {"org": "A", "ws": "X"})


def test_subset_match_thread_extra_key_fails() -> None:
    assert not matches({"org": "A", "ws": "X"}, {"org": "A"})


def test_subset_match_empty_thread_matches_any() -> None:
    assert matches({}, {})
    assert matches({}, {"org": "A"})


def test_subset_match_value_mismatch() -> None:
    assert not matches({"org": "A"}, {"org": "B"})
