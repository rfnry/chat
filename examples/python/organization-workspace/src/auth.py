from __future__ import annotations

from typing import Any

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
            metadata={"tenant": {"workspace": settings.WORKSPACE}},
        )

    user_id = raw.split(":", 1)[0] if ":" in raw else raw
    if not user_id:
        return None

    auth_dict = handshake.auth if isinstance(handshake.auth, dict) else {}
    organization = _str(auth_dict.get("organization")) or "acme_corp"
    role = _str(auth_dict.get("role")) or "member"

    return UserIdentity(
        id=user_id,
        name=user_id.replace("_", " ").title(),
        metadata={
            "tenant": {"organization": organization, "workspace": settings.WORKSPACE},
            "role": role,
        },
    )


def _read_token(handshake: HandshakeData) -> str:
    auth = handshake.auth
    if isinstance(auth, dict):
        token = _str(auth.get("token"))
        if token:
            return token
    return handshake.headers.get("authorization", "").removeprefix("Bearer ").strip()


def _str(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()
