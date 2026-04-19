import type { ContentPart, ContentPartWire } from './content'
import type { Identity, IdentityWire } from './identity'
import type { TenantScope } from './tenant'

export type EventBase = {
  id: string
  threadId: string
  runId?: string
  author: Identity
  createdAt: string
  metadata: Record<string, unknown>
  clientId?: string
  recipients: string[] | null
}

export type EventBaseWire = {
  id: string
  thread_id: string
  run_id?: string | null
  author: IdentityWire
  created_at: string
  metadata: Record<string, unknown>
  client_id?: string | null
  recipients?: string[] | null
}

export type ToolCall = {
  id: string
  name: string
  arguments: unknown
}

export type ToolResult = {
  id: string
  result?: unknown
  error?: { code: string; message: string }
}

export type MessageEvent = EventBase & { type: 'message'; content: ContentPart[] }
export type ReasoningEvent = EventBase & { type: 'reasoning'; content: string }
export type ToolCallEvent = EventBase & { type: 'tool.call'; tool: ToolCall }
export type ToolResultEvent = EventBase & { type: 'tool.result'; tool: ToolResult }
export type ThreadCreatedEvent = EventBase & {
  type: 'thread.created'
  thread: { id: string; tenant: TenantScope }
}
export type ThreadMemberAddedEvent = EventBase & {
  type: 'thread.member_added'
  member: Identity
}
export type ThreadMemberRemovedEvent = EventBase & {
  type: 'thread.member_removed'
  member: Identity
}
export type ThreadTenantChangedEvent = EventBase & {
  type: 'thread.tenant_changed'
  from: TenantScope
  to: TenantScope
}
export type RunStartedEvent = EventBase & { type: 'run.started' }
export type RunCompletedEvent = EventBase & { type: 'run.completed' }
export type RunFailedEvent = EventBase & {
  type: 'run.failed'
  error: { code: string; message: string }
}
export type RunCancelledEvent = EventBase & { type: 'run.cancelled' }

export type Event =
  | MessageEvent
  | ReasoningEvent
  | ToolCallEvent
  | ToolResultEvent
  | ThreadCreatedEvent
  | ThreadMemberAddedEvent
  | ThreadMemberRemovedEvent
  | ThreadTenantChangedEvent
  | RunStartedEvent
  | RunCompletedEvent
  | RunFailedEvent
  | RunCancelledEvent

export type EventWire = EventBaseWire & {
  type: Event['type']
} & Record<string, unknown>

export type EventDraft = {
  clientId: string
  content?: ContentPart[]
  metadata?: Record<string, unknown>
  recipients?: string[] | null
}

export type EventDraftWire = {
  client_id: string
  content?: ContentPartWire[]
  metadata?: Record<string, unknown>
  recipients?: string[] | null
}
