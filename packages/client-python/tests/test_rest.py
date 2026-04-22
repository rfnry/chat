from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from rfnry_chat_client.errors import (
    ChatAuthError,
    ThreadConflictError,
    ThreadNotFoundError,
)
from rfnry_chat_client.transport.rest import RestTransport


def _thread_payload(thread_id: str = "t_1") -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": thread_id,
        "tenant": {"org": "x"},
        "metadata": {},
        "created_at": now,
        "updated_at": now,
    }


def _make_transport(handler: httpx.MockTransport) -> RestTransport:
    return RestTransport(
        base_url="http://chat.test",
        http_client=httpx.AsyncClient(transport=handler),
    )


async def test_create_thread_posts_and_parses() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/chat/threads"
        return httpx.Response(201, json=_thread_payload())

    rest = _make_transport(httpx.MockTransport(handle))
    thread = await rest.create_thread(tenant={"org": "x"}, metadata={})
    assert thread.id == "t_1"
    assert thread.tenant == {"org": "x"}


async def test_create_thread_passes_client_id_when_provided() -> None:
    captured: list[dict[str, Any]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(201, json=_thread_payload())

    rest = _make_transport(httpx.MockTransport(handle))
    await rest.create_thread(tenant={"org": "x"}, client_id="ck-stable")
    assert captured[0]["client_id"] == "ck-stable"


async def test_create_thread_omits_client_id_when_absent() -> None:
    captured: list[dict[str, Any]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(201, json=_thread_payload())

    rest = _make_transport(httpx.MockTransport(handle))
    await rest.create_thread(tenant={"org": "x"})
    assert "client_id" not in captured[0]


async def test_get_thread_404_raises_not_found() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    rest = _make_transport(httpx.MockTransport(handle))
    with pytest.raises(ThreadNotFoundError):
        await rest.get_thread("t_missing")


async def test_auth_headers_injected() -> None:
    captured: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_thread_payload())

    async def auth() -> dict[str, str]:
        return {"authorization": "Bearer test-token"}

    rest = RestTransport(
        base_url="http://chat.test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        authenticate=auth,
    )
    await rest.get_thread("t_1")
    assert captured[0].headers["authorization"] == "Bearer test-token"


async def test_send_message_posts_draft() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/chat/threads/t_1/messages"
        body = json.loads(request.content)
        assert body["client_id"] == "c_1"
        now = datetime.now(UTC).isoformat()
        return httpx.Response(
            201,
            json={
                "id": "evt_1",
                "thread_id": "t_1",
                "run_id": None,
                "author": {"role": "user", "id": "u_1", "name": "Alice", "metadata": {}},
                "created_at": now,
                "metadata": {},
                "client_id": "c_1",
                "recipients": None,
                "type": "message",
                "content": [{"type": "text", "text": "hi"}],
            },
        )

    rest = _make_transport(httpx.MockTransport(handle))
    event = await rest.send_message(
        thread_id="t_1",
        draft={"client_id": "c_1", "content": [{"type": "text", "text": "hi"}]},
    )
    assert event.type == "message"


async def test_409_raises_thread_conflict() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, text="duplicate idempotency key")

    rest = _make_transport(httpx.MockTransport(handle))
    with pytest.raises(ThreadConflictError):
        await rest.create_thread(tenant={}, metadata={})


async def test_401_raises_auth_error() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauth")

    rest = _make_transport(httpx.MockTransport(handle))
    with pytest.raises(ChatAuthError):
        await rest.get_thread("t_1")


async def test_403_raises_auth_error() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    rest = _make_transport(httpx.MockTransport(handle))
    with pytest.raises(ChatAuthError):
        await rest.get_thread("t_1")


async def test_list_events_parses_items() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/threads/t_1/events"
        now = datetime.now(UTC).isoformat()
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "evt_1",
                        "thread_id": "t_1",
                        "run_id": None,
                        "author": {"role": "user", "id": "u_1", "name": "U", "metadata": {}},
                        "created_at": now,
                        "metadata": {},
                        "client_id": None,
                        "recipients": None,
                        "type": "message",
                        "content": [{"type": "text", "text": "hi"}],
                    }
                ],
                "next_cursor": None,
            },
        )

    rest = _make_transport(httpx.MockTransport(handle))
    page = await rest.list_events("t_1", limit=50)
    assert len(page["items"]) == 1
    assert page["items"][0].type == "message"


async def test_delete_thread_204_returns_none() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(204)

    rest = _make_transport(httpx.MockTransport(handle))
    result = await rest.delete_thread("t_1")
    assert result is None
