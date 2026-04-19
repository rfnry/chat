from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from rfnry_chat_server.protocol.identity import AssistantIdentity, Identity
from rfnry_chat_server.protocol.run import Run
from rfnry_chat_server.protocol.tenant import matches
from rfnry_chat_server.server.rest.deps import get_server, identity_tenant, resolve_identity


class InvokeBody(BaseModel):
    assistant_ids: list[str]
    idempotency_key: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class InvokeResponse(BaseModel):
    runs: list[Run]


def build_router() -> APIRouter:
    router = APIRouter(prefix="/threads/{thread_id}", tags=["invocations"])

    @router.post(
        "/invocations",
        status_code=status.HTTP_201_CREATED,
        response_model=InvokeResponse,
    )
    async def invoke(
        thread_id: str,
        body: InvokeBody,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> InvokeResponse:
        server = get_server(request)
        thread = await server.store.get_thread(thread_id)
        if thread is None or not matches(thread.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="thread not found")
        if not await server.store.is_member(thread_id, identity.id):
            raise HTTPException(status_code=403, detail="not a member of this thread")
        if not await server.check_authorize(identity, thread_id, "assistant.invoke"):
            raise HTTPException(status_code=403, detail="not authorized: assistant.invoke")
        if not body.assistant_ids:
            raise HTTPException(status_code=422, detail="assistant_ids must be non-empty")

        members = await server.store.list_members(thread_id)
        members_by_id = {m.identity_id: m for m in members}

        runs: list[Run] = []
        for assistant_id in body.assistant_ids:
            handler = server.get_handler(assistant_id)
            if handler is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"assistant not registered: {assistant_id}",
                )
            member = members_by_id.get(assistant_id)
            if member is None or not isinstance(member.identity, AssistantIdentity):
                raise HTTPException(
                    status_code=403,
                    detail=f"assistant not a member of this thread: {assistant_id}",
                )

            run = await server.executor.execute(
                thread=thread,
                assistant=member.identity,
                triggered_by=identity,
                handler=handler,
                idempotency_key=body.idempotency_key,
            )
            runs.append(run)

        return InvokeResponse(runs=runs)

    return router
