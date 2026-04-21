from __future__ import annotations

from rfnry_chat_server import HandshakeData, UserIdentity


async def authenticate(handshake: HandshakeData) -> UserIdentity | None:
    token = handshake.headers.get("authorization", "")
    if not token.startswith("Bearer "):
        auth = handshake.auth
        if isinstance(auth, dict):
            token = f"Bearer {auth.get('token', '')}"
    if not token.startswith("Bearer "):
        return None
    user_id = token.removeprefix("Bearer ").strip()
    if not user_id:
        return None
    return UserIdentity(id=user_id, name=user_id.replace("_", " ").title())
