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

    return {k: v for k, v in raw.items() if isinstance(v, str)}
