import { useState } from 'react'

export type Workspace = {
  id: 'legal' | 'medical'
  label: string
  url: string
  agentId: string
  agentName: string
  placeholder: string
}

export const WORKSPACES: Workspace[] = [
  {
    id: 'legal',
    label: 'Legal',
    url: 'http://localhost:8001',
    agentId: 'legal-agent',
    agentName: 'Legal Advisor',
    placeholder: 'What counts as a material breach?',
  },
  {
    id: 'medical',
    label: 'Medical',
    url: 'http://localhost:8002',
    agentId: 'medical-agent',
    agentName: 'Medical Reference Assistant',
    placeholder: 'Common side effects of ibuprofen?',
  },
]

export type Role = 'manager' | 'member'
export const ROLES: Role[] = ['manager', 'member']
export const ORGANIZATION = 'acme_corp'

export function useWorkspace() {
  const [id, setId] = useState<Workspace['id']>(WORKSPACES[0]!.id)
  const [role, setRole] = useState<Role>('manager')
  const active = WORKSPACES.find((w) => w.id === id) ?? WORKSPACES[0]!
  return { active, all: WORKSPACES, select: setId, role, setRole, organization: ORGANIZATION }
}
