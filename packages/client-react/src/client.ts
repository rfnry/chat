import type {
  ContentPart,
  Event,
  EventDraft,
  Identity,
  MessageEvent,
  PresenceSnapshot,
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
  identity?: Identity
  authenticate?: () => Promise<AuthenticatePayload>
  path?: string
  socketPath?: string
  fetchImpl?: typeof fetch
  reconnectionAttempts?: number
  onReconnectFailed?: () => void
}

export type { Page } from './transport/rest'

type ResolvedTransports = {
  rest: RestTransport
  socketTransport: SocketTransport
}

type ListenerEntry = {
  event: string
  handler: (data: unknown) => void
}

export class ChatClient {
  url: string
  path: string
  socketPath: string
  identity: Identity | null
  private rest: RestTransport
  private socketTransport: SocketTransport
  private fetchImpl: typeof fetch | undefined
  private authenticateFn: (() => Promise<AuthenticatePayload>) | undefined
  private readonly reconnectionAttempts: number | undefined
  private readonly onReconnectFailed: (() => void) | undefined
  private readonly listeners: ListenerEntry[] = []

  constructor(opts: ChatClientOptions) {
    this.url = opts.url.replace(/\/$/, '')
    this.path = opts.path ?? '/chat'
    this.socketPath = opts.socketPath ?? '/chat/ws'
    this.identity = opts.identity ?? null
    this.fetchImpl = opts.fetchImpl
    this.reconnectionAttempts = opts.reconnectionAttempts
    this.onReconnectFailed = opts.onReconnectFailed

    let authenticate = opts.authenticate
    if (!authenticate && opts.identity) {
      const identity = opts.identity
      const encoded = btoa(JSON.stringify(identity))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '')
      authenticate = async () => ({
        auth: { identity },
        headers: { 'x-rfnry-identity': encoded },
      })
    }
    this.authenticateFn = authenticate

    const authHeaders = authenticate ? async () => (await authenticate!()).headers ?? {} : undefined

    this.rest = new RestTransport({
      baseUrl: this.url,
      path: this.path,
      fetchImpl: opts.fetchImpl,
      authenticate: authHeaders,
    })
    this.socketTransport = new SocketTransport({
      baseUrl: this.url,
      socketPath: this.socketPath,
      authenticate,
      reconnectionAttempts: this.reconnectionAttempts,
      onReconnectFailed: this.onReconnectFailed,
    })
  }

  private _buildTransports(): ResolvedTransports {
    const authHeaders = this.authenticateFn
      ? async () => (await this.authenticateFn!()).headers ?? {}
      : undefined
    const rest = new RestTransport({
      baseUrl: this.url,
      path: this.path,
      fetchImpl: this.fetchImpl,
      authenticate: authHeaders,
    })
    const socketTransport = new SocketTransport({
      baseUrl: this.url,
      socketPath: this.socketPath,
      authenticate: this.authenticateFn,
      reconnectionAttempts: this.reconnectionAttempts,
      onReconnectFailed: this.onReconnectFailed,
    })
    return { rest, socketTransport }
  }

  createThread(input: {
    tenant?: Record<string, string>
    metadata?: Record<string, unknown>
    clientId?: string
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

  clearThreadEvents(threadId: string): Promise<void> {
    return this.rest.clearThreadEvents(threadId)
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

  listPresence(): Promise<PresenceSnapshot> {
    return this.rest.listPresence()
  }

  /**
   * Proactively open (or reuse) a thread, optionally invite a participant,
   * join, and send a message. Returns the resulting thread and event.
   *
   * - If `threadId` is omitted, creates a new thread (this client becomes first member).
   * - If `invite` is provided, adds them (add_member is idempotent server-side,
   *   so no preflight is performed).
   * - Joins the thread room.
   * - Sends the message; recipients default to `[invite.id]` if invite was specified.
   */
  async openThreadWith(opts: {
    message: ContentPart[]
    invite?: Identity
    threadId?: string
    tenant?: Record<string, string>
    metadata?: Record<string, unknown>
    clientId?: string
  }): Promise<{ thread: Thread; event: Event }> {
    const thread = opts.threadId
      ? await this.rest.getThread(opts.threadId)
      : await this.rest.createThread({
          tenant: opts.tenant,
          metadata: opts.metadata,
          clientId: opts.clientId ?? crypto.randomUUID(),
        })
    if (opts.invite) {
      // add_member is idempotent server-side — no preflight.
      await this.rest.addMember(thread.id, opts.invite)
    }
    await this.joinThread(thread.id)
    const recipients = opts.invite ? [opts.invite.id] : null
    const event = await this.rest.sendMessage(thread.id, {
      clientId: opts.clientId ?? crypto.randomUUID(),
      content: opts.message,
      recipients,
    })
    return { thread, event }
  }

  async sendTo(opts: {
    identity: Identity
    threadId?: string
    tenant?: Record<string, string>
    metadata?: Record<string, unknown>
    clientId?: string
  }): Promise<Thread> {
    const thread = opts.threadId
      ? await this.rest.getThread(opts.threadId)
      : await this.rest.createThread({
          tenant: opts.tenant,
          metadata: opts.metadata,
          clientId: opts.clientId ?? crypto.randomUUID(),
        })
    await this.rest.addMember(thread.id, opts.identity)
    await this.joinThread(thread.id)
    return thread
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
    opts: {
      triggeredBy?: Event | Identity
      triggeredByEventId?: string
      idempotencyKey?: string
    } = {}
  ): Promise<Run> {
    let triggeredByEventId = opts.triggeredByEventId
    if (triggeredByEventId === undefined && opts.triggeredBy !== undefined) {
      if (!('role' in opts.triggeredBy)) {
        triggeredByEventId = (opts.triggeredBy as Event).id
      }
    }
    const { runId } = await this.socketTransport.beginRun(threadId, {
      triggeredByEventId,
      idempotencyKey: opts.idempotencyKey,
    })
    return this.rest.getRun(runId)
  }

  async endRun(runId: string, opts: { error?: RunError } = {}): Promise<Run> {
    await this.socketTransport.endRun(runId, { error: opts.error })
    return this.rest.getRun(runId)
  }

  streamMessage(opts: {
    threadId: string
    runId: string
    author: Identity
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
    author: Identity
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

  /**
   * Tear down the current transports and rebuild them with new options,
   * preserving any listeners previously registered via `client.on(event, handler)`.
   *
   * Any option omitted keeps its current value. After this resolves the
   * socket is reconnected and all prior listeners have been re-attached to
   * the new socket — consumers do NOT need to re-register handlers.
   */
  async reconnect(
    opts: {
      url?: string
      authenticate?: () => Promise<AuthenticatePayload>
      identity?: Identity | null
      path?: string
      socketPath?: string
      fetchImpl?: typeof fetch
    } = {}
  ): Promise<void> {
    await this.socketTransport.disconnect()

    if (opts.url !== undefined) this.url = opts.url.replace(/\/$/, '')
    if (opts.path !== undefined) this.path = opts.path
    if (opts.socketPath !== undefined) this.socketPath = opts.socketPath
    if (opts.fetchImpl !== undefined) this.fetchImpl = opts.fetchImpl
    if (opts.identity !== undefined) this.identity = opts.identity
    if (opts.authenticate !== undefined) {
      this.authenticateFn = opts.authenticate
    } else if (opts.identity !== undefined && opts.identity !== null) {
      // Mirror the constructor's default-authenticate behaviour when a new
      // identity is supplied without an explicit authenticate function.
      const identity = opts.identity
      const encoded = btoa(JSON.stringify(identity))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '')
      this.authenticateFn = async () => ({
        auth: { identity },
        headers: { 'x-rfnry-identity': encoded },
      })
    }

    const { rest, socketTransport } = this._buildTransports()
    this.rest = rest
    this.socketTransport = socketTransport

    await this.socketTransport.connect()

    for (const entry of this.listeners) {
      this.socketTransport.on(entry.event, entry.handler)
    }
  }

  on(event: string, handler: (data: unknown) => void): () => void {
    const entry: ListenerEntry = { event, handler }
    this.listeners.push(entry)
    this.socketTransport.on(event, handler)
    return () => {
      const idx = this.listeners.indexOf(entry)
      if (idx !== -1) this.listeners.splice(idx, 1)
      // Detach from whichever transport is current — on reconnect we swap in
      // a new socket and the old closure's `off()` would be a no-op on the
      // now-null old socket.
      const sock = this.socketTransport.rawSocket
      if (sock) sock.off(event, handler)
    }
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
