from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from rfnry_chat_protocol import Identity, PresenceSnapshot

from rfnry_chat_server.broadcast.socketio import tenant_path as derive_tenant_path
from rfnry_chat_server.namespace import NamespaceViolation
from rfnry_chat_server.transport.rest.deps import get_server, identity_tenant, resolve_identity


def build_router() -> APIRouter:
    router = APIRouter(prefix="/presence", tags=["presence"])

    @router.get("", response_model=PresenceSnapshot)
    async def get_presence(
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> PresenceSnapshot:

        server = get_server(request)
        tenant = identity_tenant(identity)
        try:
            path = derive_tenant_path(tenant, namespace_keys=server.namespace_keys)
        except NamespaceViolation as exc:
            raise HTTPException(status_code=403, detail=f"namespace: {exc}") from exc

        members = await server.presence.list_for_tenant(path)

        return PresenceSnapshot(members=[m for m in members if m.id != identity.id])

    return router
