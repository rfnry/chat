from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from rfnry_chat_protocol import Identity

from rfnry_chat_server.server.auth import AuthenticateCallback, HandshakeData


def _default_key(handshake: HandshakeData) -> str:
    """Default cache key: the Authorization header value."""
    return handshake.headers.get("authorization", "")


def cached_authenticate(
    authenticate: AuthenticateCallback,
    *,
    ttl_seconds: float = 60.0,
    max_size: int = 1024,
    key: Callable[[HandshakeData], str] = _default_key,
) -> AuthenticateCallback:
    """Wrap an authenticate callback with a TTL+LRU cache.

    Caches both successful (Identity) and failed (None) auth results so
    repeated requests with the same token skip the upstream call. Failed
    results are cached too so an attacker can't probe token validity by
    comparing response times.

    The default cache key is the Authorization header value. For other
    schemes (cookie, auth payload, etc.) pass a custom `key` function. A
    key returning an empty string bypasses the cache (so unauthenticated
    requests don't share a single cached entry).
    """
    cache: OrderedDict[str, tuple[Identity | None, float]] = OrderedDict()

    async def cached(handshake: HandshakeData) -> Identity | None:
        cache_key = key(handshake)
        if not cache_key:
            return await authenticate(handshake)

        now = time.monotonic()
        if cache_key in cache:
            value, expires_at = cache[cache_key]
            if now < expires_at:
                cache.move_to_end(cache_key)  # mark as MRU
                return value
            # Expired — fall through to refresh.
            del cache[cache_key]

        value = await authenticate(handshake)
        # New keys land at the end of OrderedDict by default — that's the MRU
        # position. The hit path above is the only one that needs move_to_end.
        cache[cache_key] = (value, now + ttl_seconds)

        # LRU eviction
        while len(cache) > max_size:
            cache.popitem(last=False)

        return value

    return cached
