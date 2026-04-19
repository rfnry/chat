import pytest
from pydantic import ValidationError

from rfnry_chat_server.protocol.identity import (
    AssistantIdentity,
    Identity,
    SystemIdentity,
    UserIdentity,
    parse_identity,
)


def test_user_identity_minimum() -> None:
    u = UserIdentity(id="usr_1", name="Alice")
    assert u.role == "user"
    assert u.metadata == {}


def test_assistant_identity_with_metadata() -> None:
    a = AssistantIdentity(id="asst_1", name="Helper", metadata={"model": "claude"})
    assert a.role == "assistant"
    assert a.metadata == {"model": "claude"}


def test_system_identity() -> None:
    s = SystemIdentity(id="sys_webhook", name="Stripe Webhook")
    assert s.role == "system"


def test_role_field_is_immutable_per_type() -> None:
    with pytest.raises(ValidationError):
        UserIdentity(id="x", name="x", role="assistant")  # type: ignore[arg-type]


def test_parse_identity_dispatches_on_role() -> None:
    raw = {"role": "user", "id": "usr_1", "name": "Alice", "metadata": {}}
    parsed: Identity = parse_identity(raw)
    assert isinstance(parsed, UserIdentity)
    assert parsed.id == "usr_1"


def test_parse_identity_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        parse_identity({"role": "tool", "id": "x", "name": "x"})
