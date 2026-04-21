import { useState } from 'react'
import { type Workspace, WORKSPACES } from './workspaces'

export type UseWorkspace = {
  active: Workspace
  all: Workspace[]
  select: (id: Workspace['id']) => void
}

export function useWorkspace(): UseWorkspace {
  const [id, setId] = useState<Workspace['id']>(WORKSPACES[0]!.id)
  const active = WORKSPACES.find((w) => w.id === id) ?? WORKSPACES[0]!
  return { active, all: WORKSPACES, select: setId }
}
