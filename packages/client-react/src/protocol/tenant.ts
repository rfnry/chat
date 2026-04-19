export type TenantScope = Record<string, string>

export function tenantMatches(threadTenant: TenantScope, identityTenant: TenantScope): boolean {
  for (const key of Object.keys(threadTenant)) {
    if (identityTenant[key] !== threadTenant[key]) return false
  }
  return true
}
