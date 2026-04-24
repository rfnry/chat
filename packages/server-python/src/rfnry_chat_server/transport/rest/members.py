from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from rfnry_chat_protocol import Identity, Thread, ThreadMember, matches, parse_identity

from rfnry_chat_server.transport.rest.deps import get_server, identity_tenant, resolve_identity


class AddMemberBody(BaseModel):
    identity: dict[str, Any]
    role: str = "member"


def build_router() -> APIRouter:
    router = APIRouter(prefix="/threads/{thread_id}/members", tags=["members"])

    @router.get("", response_model=list[ThreadMember])
    async def list_members(
        thread_id: str,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> list[ThreadMember]:
        server = get_server(request)
        await _gate(request, thread_id, identity, "thread.read")
        return await server.store.list_members(thread_id)

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=ThreadMember)
    async def add_member(
        thread_id: str,
        body: AddMemberBody,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> ThreadMember:
        server = get_server(request)
        thread = await _gate(request, thread_id, identity, "member.add")
        new_identity = parse_identity(body.identity)
        member = await server.store.add_member(thread_id, new_identity, added_by=identity, role=body.role)
        members = await server.store.list_members(thread_id)
        await server.publish_members_updated(thread_id, [m.identity for m in members], thread=thread)
        await server.publish_thread_invited(thread, added_member=new_identity, added_by=identity)
        return member

    @router.delete("/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_member(
        thread_id: str,
        identity_id: str,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> Response:
        server = get_server(request)
        thread = await _gate(request, thread_id, identity, "member.remove")
        await server.store.remove_member(thread_id, identity_id)
        members = await server.store.list_members(thread_id)
        await server.publish_members_updated(thread_id, [m.identity for m in members], thread=thread)
        return Response(status_code=204)

    return router


async def _gate(request: Request, thread_id: str, identity: Identity, action: str) -> Thread:
    server = get_server(request)
    thread = await server.store.get_thread(thread_id)
    if thread is None or not matches(thread.tenant, identity_tenant(identity)):
        raise HTTPException(status_code=404, detail="thread not found")
    if not await server.check_authorize(identity, thread_id, action):
        raise HTTPException(status_code=403, detail=f"not authorized: {action}")
    return thread
