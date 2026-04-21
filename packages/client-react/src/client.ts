import type {
  AssistantIdentity,
  Event,
  EventDraft,
  Identity,
  MessageEvent,
  ReasoningEvent,
  Run,
  RunError,
  Thread,
  ThreadMember,
  ThreadPatch,
} from '@rfnry/chat-protocol'
import type { Socket } from 'socket.io-client'
import { Stream } from './stream'
import { type Page, RestTransport } from './transport/rest'
import { SocketTransport } from './transport/socket'

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

export type { Page } from './transport/rest'

export class ChatClient {
  readonly url: string
  readonly path: string
  readonly socketPath: string
  private readonly rest: RestTransport
  private readonly socketTransport: SocketTransport

  constructor(opts: ChatClientOptions) {
    this.url = opts.url.replace(/\/$/, '')
    this.path = opts.path ?? '/chat'
    this.socketPath = opts.socketPath ?? '/chat/ws'

    const authHeaders = opts.authenticate
      ? async () => (await opts.authenticate!()).headers ?? {}
      : undefined

    this.rest = new RestTransport({
      baseUrl: this.url,
      path: this.path,
      fetchImpl: opts.fetchImpl,
      authenticate: authHeaders,
    })
    this.socketTransport = new SocketTransport({
      baseUrl: this.url,
      socketPath: this.socketPath,
      authenticate: opts.authenticate,
    })
  }

  createThread(input: {
    tenant?: Record<string, string>
    metadata?: Record<string, unknown>
  }): Promise<Thread> {
    return this.rest.createThread(input)
  }

  getThread(threadId: string): Promise<Thread> {
    return this.rest.getThread(threadId)
  }

  listThreads(
    opts: { limit?: number; cursor?: { createdAt: string; id: string } } = {}
  ): Promise<Page<Thread>> {
    return this.rest.listThreads(opts)
  }

  updateThread(threadId: string, patch: ThreadPatch): Promise<Thread> {
    return this.rest.updateThread(threadId, patch)
  }

  deleteThread(threadId: string): Promise<void> {
    return this.rest.deleteThread(threadId)
  }

  sendMessage(threadId: string, draft: EventDraft): Promise<Event> {
    return this.rest.sendMessage(threadId, draft)
  }

  listEvents(threadId: string, opts: { limit?: number } = {}): Promise<Page<Event>> {
    return this.rest.listEvents(threadId, opts)
  }

  listMembers(threadId: string): Promise<ThreadMember[]> {
    return this.rest.listMembers(threadId)
  }

  addMember(threadId: string, identity: Identity, role = 'member'): Promise<ThreadMember> {
    return this.rest.addMember(threadId, identity, role)
  }

  removeMember(threadId: string, identityId: string): Promise<void> {
    return this.rest.removeMember(threadId, identityId)
  }

  getRun(runId: string): Promise<Run> {
    return this.rest.getRun(runId)
  }

  cancelRun(runId: string): Promise<void> {
    return this.rest.cancelRun(runId)
  }

  async emitEvent(event: Record<string, unknown> & { threadId: string }): Promise<Event> {
    return this.socketTransport.sendEvent(event.threadId, toEventWire(event))
  }

  async beginRun(
    threadId: string,
    opts: { triggeredByEventId?: string; idempotencyKey?: string } = {}
  ): Promise<Run> {
    const { runId } = await this.socketTransport.beginRun(threadId, opts)
    return this.rest.getRun(runId)
  }

  async endRun(runId: string, opts: { error?: RunError } = {}): Promise<Run> {
    await this.socketTransport.endRun(runId, { error: opts.error })
    return this.rest.getRun(runId)
  }

  streamMessage(opts: {
    threadId: string
    runId: string
    author: AssistantIdentity
    metadata?: Record<string, unknown>
    onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
  }): Stream {
    return new Stream({
      socket: this.socketTransport,
      threadId: opts.threadId,
      runId: opts.runId,
      author: opts.author,
      targetType: 'message',
      metadata: opts.metadata,
      onFinalEvent: opts.onFinalEvent,
    })
  }

  streamReasoning(opts: {
    threadId: string
    runId: string
    author: AssistantIdentity
    metadata?: Record<string, unknown>
    onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
  }): Stream {
    return new Stream({
      socket: this.socketTransport,
      threadId: opts.threadId,
      runId: opts.runId,
      author: opts.author,
      targetType: 'reasoning',
      metadata: opts.metadata,
      onFinalEvent: opts.onFinalEvent,
    })
  }

  connect(): Promise<void> {
    return this.socketTransport.connect()
  }

  disconnect(): Promise<void> {
    return this.socketTransport.disconnect()
  }

  on(event: string, handler: (data: unknown) => void): () => void {
    return this.socketTransport.on(event, handler)
  }

  joinThread(
    threadId: string,
    since?: { createdAt: string; id: string }
  ): Promise<{ threadId: string; replayed: Event[]; replayTruncated: boolean }> {
    return this.socketTransport.joinThread(threadId, since)
  }

  leaveThread(threadId: string): Promise<void> {
    return this.socketTransport.leaveThread(threadId)
  }

  get rawSocket(): Socket | null {
    return this.socketTransport.rawSocket
  }
}

function toEventWire(event: Record<string, unknown>): Record<string, unknown> {
  const copy: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(event)) {
    copy[camelToSnake(key)] = value
  }
  const author = copy.author as Record<string, unknown> | undefined
  if (author && typeof author === 'object') {
    copy.author = {
      role: author.role,
      id: author.id,
      name: author.name,
      metadata: author.metadata,
    }
  }
  return copy
}

function camelToSnake(key: string): string {
  return key.replace(/[A-Z]/g, (m) => `_${m.toLowerCase()}`)
}
