from __future__ import annotations

import hmac
import logging

from rfnry_chat_server import AssistantIdentity, HandshakeData, Identity, UserIdentity

from src.settings import settings

logger = logging.getLogger("cs.auth")


async def authenticate(handshake: HandshakeData) -> Identity | None:
    raw = _read_token(handshake)
    if not raw:
        return None

    if raw == settings.ASSISTANT_TOKEN:
        return AssistantIdentity(id=settings.ASSISTANT_ID, name=settings.ASSISTANT_NAME)

    if ":" in raw:
        user_id, _ = raw.split(":", 1)
    else:
        user_id = raw

    if not user_id:
        return None
    return UserIdentity(id=user_id, name=user_id.replace("_", " ").title())


def _read_token(handshake: HandshakeData) -> str:
    auth = handshake.auth
    if isinstance(auth, dict):
        token = str(auth.get("token") or "").strip()
        if token:
            return token
    return handshake.headers.get("authorization", "").removeprefix("Bearer ").strip()


def _equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
