from __future__ import annotations

from rfnry_chat_server.recipients import normalize_recipients


def test_none_stays_none() -> None:
    assert normalize_recipients(None, author_id="u_alice") is None


def test_empty_list_becomes_none() -> None:
    assert normalize_recipients([], author_id="u_alice") is None


def test_author_stripped() -> None:
    assert normalize_recipients(["u_alice", "assistant"], author_id="u_alice") == ["assistant"]


def test_only_author_becomes_none() -> None:
    assert normalize_recipients(["u_alice"], author_id="u_alice") is None


def test_dedup_preserves_order() -> None:
    assert normalize_recipients(["a", "b", "a", "c", "b"], author_id="x") == ["a", "b", "c"]
