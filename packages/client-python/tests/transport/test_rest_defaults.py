from __future__ import annotations

import httpx

from rfnry_chat_client.transport.rest import DEFAULT_HTTP_TIMEOUT, RestTransport


def test_default_http_client_has_finite_timeout() -> None:
    t = RestTransport(base_url="http://localhost")
    # httpx.Timeout(None) would indicate no timeout
    assert t._http.timeout != httpx.Timeout(None)
    assert t._http.timeout.read is not None


def test_default_timeout_values_are_reasonable() -> None:
    # Catches accidental loosening of the default timeout.
    assert DEFAULT_HTTP_TIMEOUT.connect == 5.0
    assert DEFAULT_HTTP_TIMEOUT.read == 30.0
    assert DEFAULT_HTTP_TIMEOUT.write == 10.0


def test_caller_provided_client_is_respected() -> None:
    custom = httpx.AsyncClient(timeout=httpx.Timeout(None, read=120.0))
    t = RestTransport(base_url="http://localhost", http_client=custom)
    # Did NOT replace the caller's client.
    assert t._http is custom
