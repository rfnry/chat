import pytest

from rfnry_chat_client.errors import (
    ChatAuthError,
    ChatHttpError,
    ThreadConflictError,
    ThreadNotFoundError,
    http_error_for,
)


def test_chat_http_error_exposes_status_and_body() -> None:
    err = ChatHttpError(500, "boom")
    assert err.status == 500
    assert err.body == "boom"
    assert "HTTP 500" in str(err)


def test_thread_not_found_error_is_404() -> None:
    err = ThreadNotFoundError("missing")
    assert err.status == 404
    assert isinstance(err, ChatHttpError)


def test_chat_auth_error_only_accepts_401_or_403() -> None:
    ChatAuthError(401, "unauth")
    ChatAuthError(403, "forbidden")
    with pytest.raises(ValueError):
        ChatAuthError(500, "wrong")  # type: ignore[arg-type]


def test_thread_conflict_error_is_409() -> None:
    err = ThreadConflictError("duplicate")
    assert err.status == 409


def test_http_error_for_dispatches() -> None:
    assert isinstance(http_error_for(404, "x"), ThreadNotFoundError)
    assert isinstance(http_error_for(401, "x"), ChatAuthError)
    assert isinstance(http_error_for(403, "x"), ChatAuthError)
    assert isinstance(http_error_for(409, "x"), ThreadConflictError)
    generic = http_error_for(500, "x")
    assert type(generic) is ChatHttpError
