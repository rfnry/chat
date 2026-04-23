from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from rfnry_chat_protocol import Identity, PresenceSnapshot

from rfnry_chat_server.broadcast.socketio import tenant_path as derive_tenant_path
from rfnry_chat_server.server.namespace import NamespaceViolation
from rfnry_chat_server.server.rest.deps import get_server, identity_tenant, resolve_identity


def build_router() -> APIRouter:
    router = APIRouter(prefix="/presence", tags=["presence"])

    @router.get("", response_model=PresenceSnapshot)
    async def get_presence(
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> PresenceSnapshot:
        # Mirror socketio/server.py on_connect: derive tenant_path from the
        # caller's identity using the same single-source-of-truth helper. If
        # this ever diverges, REST hydration and socket frames would describe
        # different scopes — clients would see ghost joins/leaves.
        server = get_server(request)
        tenant = identity_tenant(identity)
        try:
            # Defensive: resolve_identity already called enforce_namespace_on_identity,
            # so this branch is unreachable in practice. Kept for symmetry with
            # on_connect's NamespaceViolation handling (same invariant, different layer).
            path = derive_tenant_path(tenant, namespace_keys=server.namespace_keys)
        except NamespaceViolation as exc:
            raise HTTPException(status_code=403, detail=f"namespace: {exc}") from exc
        # No pagination: presence is in-memory and bounded by live-socket count
        # per tenant. Differs from list_threads intentionally.
        members = await server.presence.list_for_tenant(path)
        # Exclude the caller — they already know they're online. This matches
        # the socket on_connect `skip_sid=sid` discipline so the merged
        # REST-snapshot + live-frames view is "who's online except me".
        return PresenceSnapshot(members=[m for m in members if m.id != identity.id])

    return router
