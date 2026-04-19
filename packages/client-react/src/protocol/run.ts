import type { AssistantIdentity, Identity, IdentityWire } from './identity'

export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type RunError = {
  code: string
  message: string
}

export type Run = {
  id: string
  threadId: string
  assistant: AssistantIdentity
  triggeredBy: Identity
  status: RunStatus
  startedAt: string
  completedAt?: string
  error?: RunError
  idempotencyKey?: string
  metadata: Record<string, unknown>
}

export type RunWire = {
  id: string
  thread_id: string
  assistant: IdentityWire
  triggered_by: IdentityWire
  status: RunStatus
  started_at: string
  completed_at?: string | null
  error?: RunError | null
  idempotency_key?: string | null
  metadata: Record<string, unknown>
}
