from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from rfnry_chat_protocol import Event, EventDraft, Identity, MessageEvent, matches

from rfnry_chat_server.recipients import RecipientNotMemberError
from rfnry_chat_server.server.rest.deps import get_server, identity_tenant, resolve_identity
from rfnry_chat_server.store.types import Page


def build_router() -> APIRouter:
    router = APIRouter(prefix="/threads/{thread_id}", tags=["messages"])

    @router.post(
        "/messages",
        status_code=status.HTTP_201_CREATED,
        response_model=MessageEvent,
    )
    async def send_message(
        thread_id: str,
        draft: EventDraft,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> MessageEvent:
        server = get_server(request)
        thread = await server.store.get_thread(thread_id)
        if thread is None or not matches(thread.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="thread not found")
        if not await server.store.is_member(thread_id, identity.id):
            raise HTTPException(status_code=403, detail="not a member of this thread")
        if not await server.check_authorize(identity, thread_id, "message.send"):
            raise HTTPException(status_code=403, detail="not authorized: message.send")
        if draft.content is None:
            raise HTTPException(status_code=422, detail="message draft must include content")

        event = MessageEvent(
            id=f"evt_{secrets.token_hex(8)}",
            thread_id=thread_id,
            author=identity,
            created_at=datetime.now(UTC),
            metadata=draft.metadata,
            client_id=draft.client_id,
            recipients=draft.recipients,
            content=draft.content,
        )
        try:
            appended = await server.publish_event(event, thread=thread)
        except RecipientNotMemberError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        assert isinstance(appended, MessageEvent)
        return appended

    @router.get("/events", response_model=Page[Event])
    async def list_events(
        thread_id: str,
        request: Request,
        limit: int = 100,
        identity: Identity = Depends(resolve_identity),
    ) -> Page[Event]:
        server = get_server(request)
        thread = await server.store.get_thread(thread_id)
        if thread is None or not matches(thread.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="thread not found")
        if not await server.store.is_member(thread_id, identity.id):
            raise HTTPException(status_code=403, detail="not a member of this thread")
        if not await server.check_authorize(identity, thread_id, "thread.read"):
            raise HTTPException(status_code=403, detail="not authorized: thread.read")
        return await server.store.list_events(thread_id, limit=limit)

    return router
