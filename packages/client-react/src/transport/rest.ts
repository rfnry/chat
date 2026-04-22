import type {
  Event,
  EventDraft,
  Identity,
  Run,
  Thread,
  ThreadMember,
  ThreadPatch,
} from '@rfnry/chat-protocol'
import {
  toEvent,
  toEventDraftWire,
  toIdentityWire,
  toRun,
  toThread,
  toThreadMember,
} from '@rfnry/chat-protocol'
import { httpErrorFor } from '../errors'

export type Page<T> = {
  items: T[]
  nextCursor?: { createdAt: string; id: string } | null
}

export type AuthHeaders = () => Promise<Record<string, string>>

export type RestTransportOptions = {
  baseUrl: string
  path?: string
  fetchImpl?: typeof fetch
  authenticate?: AuthHeaders
}

export class RestTransport {
  readonly baseUrl: string
  readonly path: string
  private readonly fetchImpl: typeof fetch
  private readonly authenticate?: AuthHeaders

  constructor(opts: RestTransportOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '')
    this.path = opts.path ?? '/chat'
    this.fetchImpl = opts.fetchImpl ?? ((...args) => fetch(...args))
    this.authenticate = opts.authenticate
  }

  private async req<T>(method: string, pathname: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { 'content-type': 'application/json' }
    if (this.authenticate) {
      Object.assign(headers, await this.authenticate())
    }
    const response = await this.fetchImpl(`${this.baseUrl}${this.path}${pathname}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    if (!response.ok) {
      const text = await response.text()
      throw httpErrorFor(response.status, text)
    }
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  async createThread(input: {
    tenant?: Record<string, string>
    metadata?: Record<string, unknown>
    clientId?: string
  }): Promise<Thread> {
    const body: Record<string, unknown> = {}
    if (input.tenant !== undefined) body.tenant = input.tenant
    if (input.metadata !== undefined) body.metadata = input.metadata
    if (input.clientId !== undefined) body.client_id = input.clientId
    const wire = await this.req<Record<string, unknown>>('POST', '/threads', body)
    return toThread(wire as never)
  }

  async getThread(threadId: string): Promise<Thread> {
    const wire = await this.req<Record<string, unknown>>('GET', `/threads/${threadId}`)
    return toThread(wire as never)
  }

  async listThreads(
    opts: { limit?: number; cursor?: { createdAt: string; id: string } } = {}
  ): Promise<Page<Thread>> {
    const params = new URLSearchParams()
    if (opts.limit !== undefined) params.set('limit', String(opts.limit))
    if (opts.cursor) {
      params.set('cursor_created_at', opts.cursor.createdAt)
      params.set('cursor_id', opts.cursor.id)
    }
    const qs = params.toString()
    const wire = await this.req<{ items: unknown[]; next_cursor?: unknown }>(
      'GET',
      `/threads${qs ? `?${qs}` : ''}`
    )
    return {
      items: wire.items.map((i) => toThread(i as never)),
      nextCursor: wire.next_cursor
        ? {
            createdAt: (wire.next_cursor as { created_at: string }).created_at,
            id: (wire.next_cursor as { id: string }).id,
          }
        : null,
    }
  }

  async updateThread(threadId: string, patch: ThreadPatch): Promise<Thread> {
    const wire = await this.req<Record<string, unknown>>('PATCH', `/threads/${threadId}`, patch)
    return toThread(wire as never)
  }

  async deleteThread(threadId: string): Promise<void> {
    await this.req<void>('DELETE', `/threads/${threadId}`)
  }

  async clearThreadEvents(threadId: string): Promise<void> {
    await this.req<void>('DELETE', `/threads/${threadId}/events`)
  }

  async sendMessage(threadId: string, draft: EventDraft): Promise<Event> {
    const wire = await this.req<Record<string, unknown>>(
      'POST',
      `/threads/${threadId}/messages`,
      toEventDraftWire(draft)
    )
    return toEvent(wire as never)
  }

  async listEvents(threadId: string, opts: { limit?: number } = {}): Promise<Page<Event>> {
    const params = new URLSearchParams()
    if (opts.limit !== undefined) params.set('limit', String(opts.limit))
    const qs = params.toString()
    const wire = await this.req<{ items: unknown[]; next_cursor?: unknown }>(
      'GET',
      `/threads/${threadId}/events${qs ? `?${qs}` : ''}`
    )
    return {
      items: wire.items.map((i) => toEvent(i as never)),
      nextCursor: wire.next_cursor
        ? {
            createdAt: (wire.next_cursor as { created_at: string }).created_at,
            id: (wire.next_cursor as { id: string }).id,
          }
        : null,
    }
  }

  async listMembers(threadId: string): Promise<ThreadMember[]> {
    const wire = await this.req<unknown[]>('GET', `/threads/${threadId}/members`)
    return wire.map((m) => toThreadMember(m as never))
  }

  async addMember(threadId: string, identity: Identity, role = 'member'): Promise<ThreadMember> {
    const wire = await this.req<Record<string, unknown>>('POST', `/threads/${threadId}/members`, {
      identity: toIdentityWire(identity),
      role,
    })
    return toThreadMember(wire as never)
  }

  async removeMember(threadId: string, identityId: string): Promise<void> {
    await this.req<void>('DELETE', `/threads/${threadId}/members/${identityId}`)
  }

  async getRun(runId: string): Promise<Run> {
    const wire = await this.req<Record<string, unknown>>('GET', `/runs/${runId}`)
    return toRun(wire as never)
  }

  async cancelRun(runId: string): Promise<void> {
    await this.req<void>('DELETE', `/runs/${runId}`)
  }
}
