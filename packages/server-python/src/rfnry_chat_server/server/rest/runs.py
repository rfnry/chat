from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from rfnry_chat_protocol import Identity, Run, matches

from rfnry_chat_server.server.rest.deps import get_server, identity_tenant, resolve_identity


def build_router() -> APIRouter:
    router = APIRouter(prefix="/runs", tags=["runs"])

    @router.get("/{run_id}", response_model=Run)
    async def get_run(
        run_id: str,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> Run:
        server = get_server(request)
        run = await server.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        thread = await server.store.get_thread(run.thread_id)
        if thread is None or not matches(thread.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="run not found")
        if not await server.store.is_member(run.thread_id, identity.id):
            raise HTTPException(status_code=403, detail="not a member of this thread")
        if not await server.check_authorize(identity, run.thread_id, "thread.read"):
            raise HTTPException(status_code=403, detail="not authorized: thread.read")
        return run

    @router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def cancel_run(
        run_id: str,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> Response:
        server = get_server(request)
        run = await server.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        thread = await server.store.get_thread(run.thread_id)
        if thread is None or not matches(thread.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="run not found")
        if not await server.store.is_member(run.thread_id, identity.id):
            raise HTTPException(status_code=403, detail="not a member of this thread")
        if not await server.check_authorize(identity, run.thread_id, "run.cancel"):
            raise HTTPException(status_code=403, detail="not authorized: run.cancel")
        await server.executor.cancel(run_id)
        return Response(status_code=204)

    return router
