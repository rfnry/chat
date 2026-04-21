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
    placeholder: 'Draft an NDA termination clause…',
  },
  {
    id: 'medical',
    label: 'Medical',
    url: 'http://localhost:8002',
    agentId: 'medical-agent',
    agentName: 'Medical Reference Assistant',
    placeholder: 'Check warfarin + ibuprofen interaction…',
  },
]
