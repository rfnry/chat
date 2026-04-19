from __future__ import annotations

import re

_VALUE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MAX_VALUE_LEN = 32


class NamespaceViolation(ValueError):
    """Raised when a tenant value or namespace path violates the namespace_keys contract."""


def validate_namespace_value(value: str) -> None:
    if not value:
        raise NamespaceViolation("namespace value is empty")
    if len(value) > _MAX_VALUE_LEN:
        raise NamespaceViolation(f"namespace value too long: {len(value)} > {_MAX_VALUE_LEN}")
    if not _VALUE_RE.match(value):
        raise NamespaceViolation(f"namespace value has invalid characters: {value!r} (allowed: A-Z a-z 0-9 . _ -)")


def derive_namespace_path(
    tenant: dict[str, str],
    *,
    namespace_keys: list[str] | None,
) -> str:
    if not namespace_keys:
        return "/"
    parts: list[str] = []
    for key in namespace_keys:
        if key not in tenant:
            raise NamespaceViolation(f"tenant missing required key: {key}")
        value = tenant[key]
        if not isinstance(value, str):
            raise NamespaceViolation(f"tenant value for key {key!r} must be str, got {type(value).__name__}")
        validate_namespace_value(value)
        parts.append(value)
    return "/" + "/".join(parts)


def parse_namespace_path(
    path: str,
    *,
    namespace_keys: list[str] | None,
) -> dict[str, str]:
    if not namespace_keys:
        return {}
    if not path.startswith("/"):
        raise NamespaceViolation(f"namespace path must start with /: {path!r}")
    segments = [s for s in path.split("/") if s]
    if len(segments) != len(namespace_keys):
        raise NamespaceViolation(
            f"namespace path {path!r} expected {len(namespace_keys)} segment(s), got {len(segments)}"
        )
    result: dict[str, str] = {}
    for key, value in zip(namespace_keys, segments, strict=True):
        validate_namespace_value(value)
        result[key] = value
    return result
