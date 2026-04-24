from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.namespace import NamespaceViolation

if TYPE_CHECKING:
    from rfnry_chat_protocol import Identity

    from rfnry_chat_server.server import ChatServer


def get_server(request: Request) -> ChatServer:
    return request.app.state.chat_server  # type: ignore[no-any-return]


async def resolve_identity(request: Request) -> Identity:
    server = get_server(request)
    handshake = HandshakeData(
        headers={k.lower(): v for k, v in request.headers.items()},
        auth={},
    )
    identity = await server.authenticate(handshake)
    if identity is None:
        raise HTTPException(status_code=401, detail="unauthenticated")
    try:
        server.enforce_namespace_on_identity(identity)
    except NamespaceViolation as exc:
        raise HTTPException(status_code=403, detail=f"namespace: {exc}") from exc
    return identity


def identity_tenant(identity: Identity) -> dict[str, str]:
    raw = identity.metadata.get("tenant", {})
    if not isinstance(raw, dict):
        return {}
    # Non-string values (booleans, numbers, lists, etc.) are dropped rather
    # than coerced via str() so that a consumer who accidentally stores
    # `{"org": True}` on an identity cannot silently route to a bogus
    # `"True"` tenant key. derive_namespace_path and matches() both expect
    # str-to-str tenants, and downstream consumers can still catch the drop
    # via the "missing required key" error from derive_namespace_path.
    return {k: v for k, v in raw.items() if isinstance(v, str)}
