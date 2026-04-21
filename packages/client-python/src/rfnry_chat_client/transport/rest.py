from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from rfnry_chat_protocol import (
    Event,
    Identity,
    Run,
    Thread,
    ThreadMember,
    parse_event,
)

from rfnry_chat_client.errors import http_error_for

AuthenticateHeaders = Callable[[], Awaitable[dict[str, str]]]


class RestTransport:
    def __init__(
        self,
        *,
        base_url: str,
        http_client: httpx.AsyncClient | None = None,
        path: str = "/chat",
        authenticate: AuthenticateHeaders | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._path = path
        self._http = http_client or httpx.AsyncClient()
        self._authenticate = authenticate

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        pathname: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers: dict[str, str] = {"content-type": "application/json"}
        if self._authenticate is not None:
            headers.update(await self._authenticate())
        url = f"{self._base_url}{self._path}{pathname}"
        response = await self._http.request(
            method, url, headers=headers, json=json_body, params=params
        )
        if response.status_code >= 400:
            raise http_error_for(response.status_code, response.text)
        if response.status_code == 204:
            return None
        return response.json()

    async def create_thread(
        self,
        *,
        tenant: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Thread:
        payload = await self._request(
            "POST",
            "/threads",
            json_body={"tenant": tenant, "metadata": metadata or {}},
        )
        return Thread.model_validate(payload)

    async def get_thread(self, thread_id: str) -> Thread:
        payload = await self._request("GET", f"/threads/{thread_id}")
        return Thread.model_validate(payload)

    async def list_threads(
        self,
        *,
        limit: int | None = None,
        cursor_created_at: str | None = None,
        cursor_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor_created_at is not None and cursor_id is not None:
            params["cursor_created_at"] = cursor_created_at
            params["cursor_id"] = cursor_id
        payload = await self._request("GET", "/threads", params=params or None)
        return {
            "items": [Thread.model_validate(item) for item in payload["items"]],
            "next_cursor": payload.get("next_cursor"),
        }

    async def update_thread(self, thread_id: str, patch: dict[str, Any]) -> Thread:
        payload = await self._request("PATCH", f"/threads/{thread_id}", json_body=patch)
        return Thread.model_validate(payload)

    async def delete_thread(self, thread_id: str) -> None:
        await self._request("DELETE", f"/threads/{thread_id}")

    async def send_message(self, *, thread_id: str, draft: dict[str, Any]) -> Event:
        payload = await self._request(
            "POST", f"/threads/{thread_id}/messages", json_body=draft
        )
        return parse_event(payload)

    async def list_events(
        self, thread_id: str, *, limit: int | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        payload = await self._request(
            "GET", f"/threads/{thread_id}/events", params=params or None
        )
        return {
            "items": [parse_event(item) for item in payload["items"]],
            "next_cursor": payload.get("next_cursor"),
        }

    async def list_members(self, thread_id: str) -> list[ThreadMember]:
        payload = await self._request("GET", f"/threads/{thread_id}/members")
        return [ThreadMember.model_validate(item) for item in payload]

    async def add_member(
        self,
        thread_id: str,
        *,
        identity: Identity,
        role: str = "member",
    ) -> ThreadMember:
        payload = await self._request(
            "POST",
            f"/threads/{thread_id}/members",
            json_body={"identity": identity.model_dump(mode="json"), "role": role},
        )
        return ThreadMember.model_validate(payload)

    async def remove_member(self, thread_id: str, identity_id: str) -> None:
        await self._request("DELETE", f"/threads/{thread_id}/members/{identity_id}")

    async def get_run(self, run_id: str) -> Run:
        payload = await self._request("GET", f"/runs/{run_id}")
        return Run.model_validate(payload)

    async def cancel_run(self, run_id: str) -> None:
        await self._request("DELETE", f"/runs/{run_id}")
