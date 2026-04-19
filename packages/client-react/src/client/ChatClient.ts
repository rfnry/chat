import { io, type Socket } from 'socket.io-client'
import type { Event, EventDraft } from '../protocol/event'
import type { Identity } from '../protocol/identity'
import {
  toEvent,
  toEventDraftWire,
  toIdentityWire,
  toRun,
  toThread,
  toThreadMember,
} from '../protocol/mappers'
import type { Run } from '../protocol/run'
import type { Thread, ThreadMember, ThreadPatch } from '../protocol/thread'

export type AuthenticatePayload = {
  headers?: Record<string, string>
  auth?: Record<string, unknown>
}

export type ChatClientOptions = {
  url: string
  authenticate?: () => Promise<AuthenticatePayload>
  path?: string
  socketPath?: string
  fetchImpl?: typeof fetch
}

export type Page<T> = {
  items: T[]
  nextCursor?: { createdAt: string; id: string } | null
}

export class ChatHttpError extends Error {
  constructor(
    readonly status: number,
    readonly body: string
  ) {
    super(`HTTP ${status}: ${body}`)
    this.name = 'ChatHttpError'
  }
}

/** Thrown on HTTP 404. */
export class ThreadNotFoundError extends ChatHttpError {
  constructor(body: string) {
    super(404, body)
    this.name = 'ThreadNotFoundError'
  }
}

/** Thrown on HTTP 401 or 403. */
export class ChatAuthError extends ChatHttpError {
  constructor(status: 401 | 403, body: string) {
    super(status, body)
    this.name = 'ChatAuthError'
  }
}

/**
 * Thrown on HTTP 409, typically from an idempotency-key collision on
 * `POST /threads/:id/invocations` — same key submitted with a different
 * assistant set.
 */
export class ThreadConflictError extends ChatHttpError {
  constructor(body: string) {
    super(409, body)
    this.name = 'ThreadConflictError'
  }
}

function httpErrorFor(status: number, body: string): ChatHttpError {
  if (status === 404) return new ThreadNotFoundError(body)
  if (status === 401 || status === 403) return new ChatAuthError(status, body)
  if (status === 409) return new ThreadConflictError(body)
  return new ChatHttpError(status, body)
}

export class ChatClient {
  readonly url: string
  readonly path: string
  readonly socketPath: string
  private readonly authenticate?: ChatClientOptions['authenticate']
  private readonly fetchImpl: typeof fetch
  private socket: Socket | null = null

  constructor(opts: ChatClientOptions) {
    this.url = opts.url.replace(/\/$/, '')
    this.path = opts.path ?? '/chat'
    this.socketPath = opts.socketPath ?? '/chat/ws'
    this.authenticate = opts.authenticate
    this.fetchImpl = opts.fetchImpl ?? ((...args) => fetch(...args))
  }

  private async authHeaders(): Promise<Record<string, string>> {
    if (!this.authenticate) return {}
    const result = await this.authenticate()
    return result.headers ?? {}
  }

  private async req<T>(method: string, pathname: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {
      'content-type': 'application/json',
      ...(await this.authHeaders()),
    }
    const response = await this.fetchImpl(`${this.url}${this.path}${pathname}`, {
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
  }): Promise<Thread> {
    const wire = await this.req<Record<string, unknown>>('POST', '/threads', input)
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

  async invoke(
    threadId: string,
    body: {
      assistantIds: string[]
      idempotencyKey?: string
      options?: Record<string, unknown>
    }
  ): Promise<{ runs: Run[] }> {
    const wire = await this.req<{ runs: unknown[] }>('POST', `/threads/${threadId}/invocations`, {
      assistant_ids: body.assistantIds,
      idempotency_key: body.idempotencyKey,
      options: body.options ?? {},
    })
    return { runs: wire.runs.map((r) => toRun(r as never)) }
  }

  async getRun(runId: string): Promise<Run> {
    const wire = await this.req<Record<string, unknown>>('GET', `/runs/${runId}`)
    return toRun(wire as never)
  }

  async cancelRun(runId: string): Promise<void> {
    await this.req<void>('DELETE', `/runs/${runId}`)
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

  async connect(): Promise<void> {
    const auth = this.authenticate ? ((await this.authenticate()).auth ?? {}) : {}
    const socket = io(this.url, {
      path: this.socketPath,
      transports: ['websocket'],
      auth,
    })
    this.socket = socket
    await new Promise<void>((resolve, reject) => {
      socket.once('connect', () => resolve())
      socket.once('connect_error', (err) => reject(err))
    })
  }

  async disconnect(): Promise<void> {
    if (this.socket) {
      this.socket.disconnect()
      this.socket = null
    }
  }

  on(event: string, handler: (data: unknown) => void): () => void {
    if (!this.socket) throw new Error('not connected')
    this.socket.on(event, handler)
    return () => this.socket?.off(event, handler)
  }

  async joinThread(
    threadId: string,
    since?: { createdAt: string; id: string }
  ): Promise<{ threadId: string; replayed: Event[]; replayTruncated: boolean }> {
    if (!this.socket) throw new Error('not connected')
    const payload: Record<string, unknown> = { thread_id: threadId }
    if (since) {
      payload.since = { created_at: since.createdAt, id: since.id }
    }
    const response = (await this.socket.emitWithAck('thread:join', payload)) as {
      thread_id?: string
      replayed?: unknown[]
      replay_truncated?: boolean
      error?: { code: string; message: string }
    }
    if (response.error) {
      throw new ChatHttpError(0, `${response.error.code}: ${response.error.message}`)
    }
    return {
      threadId: response.thread_id ?? threadId,
      replayed: (response.replayed ?? []).map((e) => toEvent(e as never)),
      replayTruncated: response.replay_truncated ?? false,
    }
  }

  async leaveThread(threadId: string): Promise<void> {
    if (!this.socket) throw new Error('not connected')
    await this.socket.emitWithAck('thread:leave', { thread_id: threadId })
  }

  get rawSocket(): Socket | null {
    return this.socket
  }
}
