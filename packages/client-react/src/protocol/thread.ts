import type { Identity, IdentityWire } from './identity'
import type { TenantScope } from './tenant'

export type Thread = {
  id: string
  tenant: TenantScope
  metadata: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

export type ThreadWire = {
  id: string
  tenant: TenantScope
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type ThreadMember = {
  threadId: string
  identityId: string
  identity: Identity
  role: string
  addedAt: string
  addedBy: Identity
}

export type ThreadMemberWire = {
  thread_id: string
  identity_id: string
  identity: IdentityWire
  role: string
  added_at: string
  added_by: IdentityWire
}

export type ThreadPatch = {
  tenant?: TenantScope
  metadata?: Record<string, unknown>
}
