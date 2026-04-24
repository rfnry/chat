from __future__ import annotations

import pytest

from rfnry_chat_server.namespace import (
    NamespaceViolation,
    derive_namespace_path,
    parse_namespace_path,
    validate_namespace_value,
)


class TestValidateNamespaceValue:
    def test_accepts_alphanumeric(self) -> None:
        validate_namespace_value("orgA")
        validate_namespace_value("Org_123")
        validate_namespace_value("tenant.name")
        validate_namespace_value("a-b")

    def test_rejects_empty(self) -> None:
        with pytest.raises(NamespaceViolation, match="empty"):
            validate_namespace_value("")

    def test_rejects_slash(self) -> None:
        with pytest.raises(NamespaceViolation, match="invalid characters"):
            validate_namespace_value("a/b")

    def test_rejects_whitespace(self) -> None:
        with pytest.raises(NamespaceViolation, match="invalid characters"):
            validate_namespace_value("a b")

    def test_rejects_longer_than_32_chars(self) -> None:
        with pytest.raises(NamespaceViolation, match="too long"):
            validate_namespace_value("a" * 33)

    def test_accepts_exactly_32_chars(self) -> None:
        validate_namespace_value("a" * 32)


class TestDeriveNamespacePath:
    def test_returns_root_when_no_keys(self) -> None:
        assert derive_namespace_path({"org": "A"}, namespace_keys=None) == "/"
        assert derive_namespace_path({"org": "A"}, namespace_keys=[]) == "/"

    def test_single_key(self) -> None:
        assert derive_namespace_path({"org": "A"}, namespace_keys=["org"]) == "/A"

    def test_multiple_keys_order_preserved(self) -> None:
        assert (
            derive_namespace_path(
                {"org": "A", "ws": "X", "extra": "zzz"},
                namespace_keys=["org", "ws"],
            )
            == "/A/X"
        )

    def test_reversed_key_order_gives_different_path(self) -> None:
        assert (
            derive_namespace_path(
                {"org": "A", "ws": "X"},
                namespace_keys=["ws", "org"],
            )
            == "/X/A"
        )

    def test_missing_key_raises(self) -> None:
        with pytest.raises(NamespaceViolation, match="missing required key: org"):
            derive_namespace_path({"ws": "X"}, namespace_keys=["org", "ws"])

    def test_non_string_value_raises(self) -> None:
        with pytest.raises(NamespaceViolation, match="must be str"):
            derive_namespace_path({"org": 42}, namespace_keys=["org"])  # type: ignore[dict-item]

    def test_invalid_char_propagates(self) -> None:
        with pytest.raises(NamespaceViolation, match="invalid characters"):
            derive_namespace_path({"org": "a/b"}, namespace_keys=["org"])


class TestParseNamespacePath:
    def test_root_returns_empty(self) -> None:
        assert parse_namespace_path("/", namespace_keys=None) == {}
        assert parse_namespace_path("/", namespace_keys=[]) == {}

    def test_single_key(self) -> None:
        assert parse_namespace_path("/A", namespace_keys=["org"]) == {"org": "A"}

    def test_multiple_keys(self) -> None:
        assert parse_namespace_path("/A/X", namespace_keys=["org", "ws"]) == {"org": "A", "ws": "X"}

    def test_segment_count_mismatch(self) -> None:
        with pytest.raises(NamespaceViolation, match="expected 2 segment"):
            parse_namespace_path("/A", namespace_keys=["org", "ws"])
        with pytest.raises(NamespaceViolation, match="expected 1 segment"):
            parse_namespace_path("/A/X", namespace_keys=["org"])

    def test_root_with_keys_required(self) -> None:
        with pytest.raises(NamespaceViolation, match="expected 1 segment"):
            parse_namespace_path("/", namespace_keys=["org"])

    def test_missing_leading_slash(self) -> None:
        with pytest.raises(NamespaceViolation, match="must start with /"):
            parse_namespace_path("A/X", namespace_keys=["org", "ws"])

    def test_invalid_char_propagates(self) -> None:
        with pytest.raises(NamespaceViolation, match="invalid characters"):
            parse_namespace_path("/a b", namespace_keys=["org"])

    def test_round_trip(self) -> None:
        tenant = {"org": "Org_A", "ws": "ws-1"}
        keys = ["org", "ws"]
        path = derive_namespace_path(tenant, namespace_keys=keys)
        assert parse_namespace_path(path, namespace_keys=keys) == tenant
