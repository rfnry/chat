from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from rfnry_chat_protocol import (
    Identity,
    Thread,
    ThreadDraft,
    ThreadPatch,
    ThreadTenantChangedEvent,
    matches,
)

from rfnry_chat_server.server.rest.deps import get_server, identity_tenant, resolve_identity
from rfnry_chat_server.store.types import Page, ThreadCursor

MAX_THREADS_LIMIT = 200


def build_router() -> APIRouter:
    router = APIRouter(prefix="/threads", tags=["threads"])

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=Thread)
    async def create_thread(
        body: ThreadDraft,
        request: Request,
        response: Response,
        identity: Identity = Depends(resolve_identity),
    ) -> Thread:
        server = get_server(request)
        if server.namespace_keys is not None:
            missing = [k for k in server.namespace_keys if k not in body.tenant]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"namespace_keys required but missing: {missing}",
                )
        if body.client_id is not None:
            existing = await server.store.find_thread_by_client_id(identity.id, body.client_id)
            if existing is not None:
                response.status_code = status.HTTP_200_OK
                return existing
        now = datetime.now(UTC)
        thread = Thread(
            id=f"th_{secrets.token_hex(8)}",
            tenant=body.tenant,
            metadata=body.metadata,
            created_at=now,
            updated_at=now,
        )
        created = await server.store.create_thread(
            thread,
            caller_identity_id=identity.id,
            client_id=body.client_id,
        )
        await server.store.add_member(created.id, identity, added_by=identity)
        members = await server.store.list_members(created.id)
        await server.publish_members_updated(created.id, [m.identity for m in members], thread=created)
        await server.publish_thread_created(created)
        return created

    @router.get("", response_model=Page[Thread])
    async def list_threads(
        request: Request,
        limit: int = 50,
        cursor_created_at: str | None = None,
        cursor_id: str | None = None,
        identity: Identity = Depends(resolve_identity),
    ) -> Page[Thread]:
        server = get_server(request)
        cursor = None
        if cursor_created_at and cursor_id:
            cursor = ThreadCursor(
                created_at=datetime.fromisoformat(cursor_created_at),
                id=cursor_id,
            )
        effective_limit = min(max(limit, 1), MAX_THREADS_LIMIT)
        return await server.store.list_threads(
            tenant_filter=identity_tenant(identity),
            cursor=cursor,
            limit=effective_limit,
            member_identity_id=identity.id,
        )

    @router.get("/{thread_id}", response_model=Thread)
    async def get_thread(
        thread_id: str,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> Thread:
        server = get_server(request)
        thread = await server.store.get_thread(thread_id)
        if thread is None or not matches(thread.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="thread not found")
        if not await server.check_authorize(identity, thread_id, "thread.read"):
            raise HTTPException(status_code=403, detail="not authorized: thread.read")
        return thread

    @router.patch("/{thread_id}", response_model=Thread)
    async def patch_thread(
        thread_id: str,
        body: ThreadPatch,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> Thread:
        server = get_server(request)
        existing = await server.store.get_thread(thread_id)
        if existing is None or not matches(existing.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="thread not found")
        if not await server.check_authorize(identity, thread_id, "thread.update"):
            raise HTTPException(status_code=403, detail="not authorized: thread.update")

        old_tenant = existing.tenant
        updated = await server.store.update_thread(thread_id, body)

        if body.tenant is not None and body.tenant != old_tenant:
            event = ThreadTenantChangedEvent.model_validate(
                {
                    "id": f"evt_{secrets.token_hex(8)}",
                    "thread_id": thread_id,
                    "author": identity.model_dump(mode="json"),
                    "created_at": datetime.now(UTC),
                    "type": "thread.tenant_changed",
                    "from": old_tenant,
                    "to": body.tenant,
                }
            )
            await server.publish_event(event, thread=updated)
        await server.publish_thread_updated(updated)
        return updated

    @router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_thread(
        thread_id: str,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> Response:
        server = get_server(request)
        existing = await server.store.get_thread(thread_id)
        if existing is None or not matches(existing.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="thread not found")
        if not await server.check_authorize(identity, thread_id, "thread.delete"):
            raise HTTPException(status_code=403, detail="not authorized: thread.delete")
        await server.store.delete_thread(thread_id)
        await server.publish_thread_deleted(thread_id, existing.tenant)
        return Response(status_code=204)

    @router.delete("/{thread_id}/events", status_code=status.HTTP_204_NO_CONTENT)
    async def clear_thread_events(
        thread_id: str,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> Response:
        server = get_server(request)
        existing = await server.store.get_thread(thread_id)
        if existing is None or not matches(existing.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="thread not found")
        if not await server.check_authorize(identity, thread_id, "thread.clear"):
            raise HTTPException(status_code=403, detail="not authorized: thread.clear")
        await server.store.clear_events(thread_id)
        await server.publish_thread_cleared(thread_id, thread=existing)
        return Response(status_code=204)

    return router
