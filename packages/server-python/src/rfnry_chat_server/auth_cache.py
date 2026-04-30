from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from rfnry_chat_protocol import Identity

from rfnry_chat_server.auth import AuthenticateCallback, HandshakeData


def _default_key(handshake: HandshakeData) -> str:

    return handshake.headers.get("authorization", "")


def cached_authenticate(
    authenticate: AuthenticateCallback,
    *,
    ttl_seconds: float = 60.0,
    max_size: int = 1024,
    key: Callable[[HandshakeData], str] = _default_key,
) -> AuthenticateCallback:

    cache: OrderedDict[str, tuple[Identity | None, float]] = OrderedDict()

    async def cached(handshake: HandshakeData) -> Identity | None:
        cache_key = key(handshake)
        if not cache_key:
            return await authenticate(handshake)

        now = time.monotonic()
        if cache_key in cache:
            value, expires_at = cache[cache_key]
            if now < expires_at:
                cache.move_to_end(cache_key)
                return value

            del cache[cache_key]

        value = await authenticate(handshake)

        cache[cache_key] = (value, now + ttl_seconds)

        while len(cache) > max_size:
            cache.popitem(last=False)

        return value

    return cached
