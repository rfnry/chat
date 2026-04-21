from __future__ import annotations

from rfnry_chat_server import AssistantIdentity, HandshakeData, Identity, UserIdentity

from src.settings import settings


async def authenticate(handshake: HandshakeData) -> Identity | None:
    raw = _read_token(handshake)
    if not raw:
        return None

    if raw == settings.ASSISTANT_TOKEN:
        return AssistantIdentity(
            id=settings.ASSISTANT_ID,
            name=settings.ASSISTANT_NAME,
            metadata={"workspace": settings.WORKSPACE},
        )

    user_id = raw.split(":", 1)[0] if ":" in raw else raw
    if not user_id:
        return None
    return UserIdentity(
        id=user_id,
        name=user_id.replace("_", " ").title(),
        metadata={"workspace": settings.WORKSPACE},
    )


def _read_token(handshake: HandshakeData) -> str:
    auth = handshake.auth
    if isinstance(auth, dict):
        token = str(auth.get("token") or "").strip()
        if token:
            return token
    return handshake.headers.get("authorization", "").removeprefix("Bearer ").strip()
