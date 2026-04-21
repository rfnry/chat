import { useState } from 'react'
import { type Workspace, WORKSPACES } from './workspaces'

export type Role = 'manager' | 'member'

export const ROLES: Role[] = ['manager', 'member']

export const ORGANIZATION = 'acme_corp'

export type UseWorkspace = {
  active: Workspace
  all: Workspace[]
  select: (id: Workspace['id']) => void
  role: Role
  setRole: (role: Role) => void
  organization: string
}

export function useWorkspace(): UseWorkspace {
  const [id, setId] = useState<Workspace['id']>(WORKSPACES[0]!.id)
  const [role, setRole] = useState<Role>('manager')
  const active = WORKSPACES.find((w) => w.id === id) ?? WORKSPACES[0]!
  return {
    active,
    all: WORKSPACES,
    select: setId,
    role,
    setRole,
    organization: ORGANIZATION,
  }
}
