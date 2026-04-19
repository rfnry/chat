from __future__ import annotations

TenantScope = dict[str, str]


def matches(thread_tenant: TenantScope, identity_tenant: TenantScope) -> bool:
    for key, value in thread_tenant.items():
        if identity_tenant.get(key) != value:
            return False
    return True
