from __future__ import annotations

import asyncio

from rfnry_chat_protocol import Identity


class PresenceRegistry:
    def __init__(self) -> None:
        self._sids: dict[str, set[str]] = {}
        self._identities: dict[str, Identity] = {}
        self._tenant_paths: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def add(
        self,
        identity_id: str,
        sid: str,
        identity: Identity,
        *,
        tenant_path: str,
    ) -> bool:
        async with self._lock:
            sids = self._sids.setdefault(identity_id, set())
            was_empty = not sids
            existing_tp = self._tenant_paths.get(identity_id)
            if existing_tp is not None and existing_tp != tenant_path:
                raise ValueError(
                    f"identity {identity_id!r} already registered under tenant_path "
                    f"{existing_tp!r}; refusing re-add under {tenant_path!r}. "
                    f"This indicates an upstream auth bug — same identity should "
                    f"resolve to the same tenant_path on every socket."
                )
            sids.add(sid)
            self._identities[identity_id] = identity
            self._tenant_paths[identity_id] = tenant_path
            return was_empty

    async def remove(
        self,
        identity_id: str,
        sid: str,
    ) -> tuple[bool, Identity | None, str | None]:
        async with self._lock:
            sids = self._sids.get(identity_id)
            if not sids:
                return False, None, None
            sids.discard(sid)
            if sids:
                return False, None, None
            del self._sids[identity_id]
            ident = self._identities.pop(identity_id, None)
            tp = self._tenant_paths.pop(identity_id, None)
            return True, ident, tp

    async def list_for_tenant(self, tenant_path: str) -> list[Identity]:
        async with self._lock:
            return [self._identities[iid] for iid, tp in self._tenant_paths.items() if tp == tenant_path]
