import type {
  AudioPart,
  AudioPartWire,
  ContentPart,
  ContentPartWire,
  FormPart,
  FormPartWire,
} from './content'
import type { Event, EventDraft, EventDraftWire, EventWire } from './event'
import type { AssistantIdentity, Identity, IdentityWire } from './identity'
import type { Run, RunWire } from './run'
import type { Thread, ThreadMember, ThreadMemberWire, ThreadWire } from './thread'

export function toIdentity(wire: IdentityWire): Identity {
  return {
    role: wire.role,
    id: wire.id,
    name: wire.name,
    metadata: wire.metadata ?? {},
  } as Identity
}

export function toIdentityWire(domain: Identity): IdentityWire {
  return {
    role: domain.role,
    id: domain.id,
    name: domain.name,
    metadata: domain.metadata ?? {},
  }
}

export function toContentPart(wire: ContentPartWire): ContentPart {
  switch (wire.type) {
    case 'text':
      return wire
    case 'image':
      return wire
    case 'audio': {
      const a = wire as AudioPartWire
      const out: AudioPart = {
        type: 'audio',
        url: a.url,
        mime: a.mime,
        name: a.name,
        size: a.size,
        durationMs: a.duration_ms,
      }
      return out
    }
    case 'document':
      return wire
    case 'form': {
      const f = wire as FormPartWire
      const out: FormPart = {
        type: 'form',
        formId: f.form_id,
        schema: f.schema,
        status: f.status,
        values: f.values,
        answersEventId: f.answers_event_id,
        title: f.title,
        description: f.description,
      }
      return out
    }
  }
}

export function toContentPartWire(domain: ContentPart): ContentPartWire {
  switch (domain.type) {
    case 'text':
      return domain
    case 'image':
      return domain
    case 'audio':
      return {
        type: 'audio',
        url: domain.url,
        mime: domain.mime,
        name: domain.name,
        size: domain.size,
        duration_ms: domain.durationMs,
      }
    case 'document':
      return domain
    case 'form':
      return {
        type: 'form',
        form_id: domain.formId,
        schema: domain.schema,
        status: domain.status,
        values: domain.values,
        answers_event_id: domain.answersEventId,
        title: domain.title,
        description: domain.description,
      }
  }
}

export function toThread(wire: ThreadWire): Thread {
  return {
    id: wire.id,
    tenant: wire.tenant ?? {},
    metadata: wire.metadata ?? {},
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  }
}

export function toThreadMember(wire: ThreadMemberWire): ThreadMember {
  return {
    threadId: wire.thread_id,
    identityId: wire.identity_id,
    identity: toIdentity(wire.identity),
    role: wire.role,
    addedAt: wire.added_at,
    addedBy: toIdentity(wire.added_by),
  }
}

export function toRun(wire: RunWire): Run {
  return {
    id: wire.id,
    threadId: wire.thread_id,
    assistant: toIdentity(wire.assistant) as AssistantIdentity,
    triggeredBy: toIdentity(wire.triggered_by),
    status: wire.status,
    startedAt: wire.started_at,
    completedAt: wire.completed_at ?? undefined,
    error: wire.error ?? undefined,
    idempotencyKey: wire.idempotency_key ?? undefined,
    metadata: wire.metadata ?? {},
  }
}

export function toEvent(wire: EventWire): Event {
  const base = {
    id: wire.id,
    threadId: wire.thread_id,
    runId: wire.run_id ?? undefined,
    author: toIdentity(wire.author),
    createdAt: wire.created_at,
    metadata: wire.metadata ?? {},
    clientId: wire.client_id ?? undefined,
    recipients: wire.recipients ?? null,
  }
  switch (wire.type) {
    case 'message':
      return {
        ...base,
        type: 'message',
        content: ((wire.content as ContentPartWire[]) ?? []).map(toContentPart),
      } as Event
    case 'reasoning':
      return { ...base, type: 'reasoning', content: wire.content as string } as Event
    case 'tool.call':
      return { ...base, type: 'tool.call', tool: wire.tool as never } as Event
    case 'tool.result':
      return { ...base, type: 'tool.result', tool: wire.tool as never } as Event
    case 'thread.created':
      return {
        ...base,
        type: 'thread.created',
        thread: wire.thread as { id: string; tenant: Record<string, string> },
      } as Event
    case 'thread.member_added':
      return {
        ...base,
        type: 'thread.member_added',
        member: toIdentity(wire.member as IdentityWire),
      } as Event
    case 'thread.member_removed':
      return {
        ...base,
        type: 'thread.member_removed',
        member: toIdentity(wire.member as IdentityWire),
      } as Event
    case 'thread.tenant_changed':
      return {
        ...base,
        type: 'thread.tenant_changed',
        from: wire.from as Record<string, string>,
        to: wire.to as Record<string, string>,
      } as Event
    case 'run.started':
      return { ...base, type: 'run.started' } as Event
    case 'run.completed':
      return { ...base, type: 'run.completed' } as Event
    case 'run.failed':
      return {
        ...base,
        type: 'run.failed',
        error: wire.error as { code: string; message: string },
      } as Event
    case 'run.cancelled':
      return { ...base, type: 'run.cancelled' } as Event
    default:
      return base as Event
  }
}

export function toEventDraftWire(domain: EventDraft): EventDraftWire {
  return {
    client_id: domain.clientId,
    content: domain.content?.map(toContentPartWire),
    metadata: domain.metadata,
    recipients: domain.recipients ?? null,
  }
}
