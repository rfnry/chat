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
  ToolCallEvent,
  ToolResultEvent,
} from '@rfnry/chat-protocol'
import type { Socket } from 'socket.io-client'
import { ChatStream } from './stream'
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

export type WithRunSend = {
  threadId: string
  runId: string | null
  message: (
    content: ContentPart[],
    opts?: { recipients?: string[]; metadata?: Record<string, unknown> }
  ) => Promise<MessageEvent>
  reasoning: (
    text: string,
    opts?: { recipients?: string[]; metadata?: Record<string, unknown> }
  ) => Promise<ReasoningEvent>
  toolCall: (
    name: string,
    args: unknown,
    opts?: { id?: string; recipients?: string[]; metadata?: Record<string, unknown> }
  ) => Promise<ToolCallEvent>
  toolResult: (
    toolId: string,
    result?: unknown,
    opts?: {
      error?: { code: string; message: string }
      recipients?: string[]
      metadata?: Record<string, unknown>
    }
  ) => Promise<ToolResultEvent>
  emit: <E extends Event>(event: E) => Promise<E>
  streamMessage: (opts?: {
    author?: Identity
    metadata?: Record<string, unknown>
    onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
  }) => ChatStream
  streamReasoning: (opts?: {
    author?: Identity
    metadata?: Record<string, unknown>
    onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
  }) => ChatStream
}

export type WithRunOptions = {
  triggeredBy?: Event | Identity
  triggeredByEventId?: string
  idempotencyKey?: string
  lazy?: boolean
}

type ResolvedTransports = {
  rest: RestTransport
  socket: SocketTransport
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
  private socket: SocketTransport
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

    const { rest, socket } = this._buildTransports()
    this.rest = rest
    this.socket = socket
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
    const socket = new SocketTransport({
      baseUrl: this.url,
      socketPath: this.socketPath,
      authenticate: this.authenticateFn,
      reconnectionAttempts: this.reconnectionAttempts,
      onReconnectFailed: this.onReconnectFailed,
    })
    return { rest, socket }
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
    return this.socket.sendEvent(event.threadId, toEventWire(event))
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
    const { runId } = await this.socket.beginRun(threadId, {
      triggeredByEventId,
      idempotencyKey: opts.idempotencyKey,
    })
    return this.rest.getRun(runId)
  }

  async endRun(runId: string, opts: { error?: RunError } = {}): Promise<Run> {
    await this.socket.endRun(runId, { error: opts.error })
    return this.rest.getRun(runId)
  }

  streamMessage(opts: {
    threadId: string
    runId: string
    author: Identity
    metadata?: Record<string, unknown>
    onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
  }): ChatStream {
    return new ChatStream({
      socket: this.socket,
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
  }): ChatStream {
    return new ChatStream({
      socket: this.socket,
      threadId: opts.threadId,
      runId: opts.runId,
      author: opts.author,
      targetType: 'reasoning',
      metadata: opts.metadata,
      onFinalEvent: opts.onFinalEvent,
    })
  }

  async withRun<T>(
    threadId: string,
    callback: (send: WithRunSend) => Promise<T>,
    opts: WithRunOptions = {}
  ): Promise<T> {
    if (!threadId) throw new Error('threadId is required')
    const author = this.identity
    if (!author) throw new Error('withRun requires an authenticated identity')

    let runId: string | null = null
    const startRun = async (): Promise<string> => {
      if (runId) return runId
      const run = await this.beginRun(threadId, {
        triggeredBy: opts.triggeredBy,
        triggeredByEventId: opts.triggeredByEventId,
        idempotencyKey: opts.idempotencyKey,
      })
      runId = run.id
      return runId
    }

    if (!opts.lazy) await startRun()

    const buildBase = async () => {
      const rid = await startRun()
      return {
        id: `evt_${crypto.randomUUID().replace(/-/g, '').slice(0, 16)}`,
        thread_id: threadId,
        run_id: rid,
        author,
        created_at: new Date().toISOString(),
        metadata: {} as Record<string, unknown>,
      }
    }

    const send: WithRunSend = {
      threadId,
      get runId() {
        return runId
      },
      message: async (content, msgOpts = {}) => {
        const base = await buildBase()
        const event = {
          ...base,
          type: 'message' as const,
          content,
          metadata: msgOpts.metadata ?? {},
          recipients: msgOpts.recipients ?? null,
        }
        return (await this.emitEvent(
          event as unknown as Record<string, unknown> & { threadId: string }
        )) as MessageEvent
      },
      reasoning: async (text, msgOpts = {}) => {
        const base = await buildBase()
        const event = {
          ...base,
          type: 'reasoning' as const,
          content: text,
          metadata: msgOpts.metadata ?? {},
          recipients: msgOpts.recipients ?? null,
        }
        return (await this.emitEvent(
          event as unknown as Record<string, unknown> & { threadId: string }
        )) as ReasoningEvent
      },
      toolCall: async (name, args, toolOpts = {}) => {
        const base = await buildBase()
        const event = {
          ...base,
          type: 'tool.call' as const,
          tool: {
            id: toolOpts.id ?? `call_${crypto.randomUUID().replace(/-/g, '').slice(0, 16)}`,
            name,
            arguments: args,
          },
          metadata: toolOpts.metadata ?? {},
          recipients: toolOpts.recipients ?? null,
        }
        return (await this.emitEvent(
          event as unknown as Record<string, unknown> & { threadId: string }
        )) as ToolCallEvent
      },
      toolResult: async (toolId, result, toolOpts = {}) => {
        const base = await buildBase()
        const event = {
          ...base,
          type: 'tool.result' as const,
          tool: { id: toolId, result, error: toolOpts.error ?? null },
          metadata: toolOpts.metadata ?? {},
          recipients: toolOpts.recipients ?? null,
        }
        return (await this.emitEvent(
          event as unknown as Record<string, unknown> & { threadId: string }
        )) as ToolResultEvent
      },
      emit: async (event) => {
        const rid = await startRun()
        const stamped = {
          ...(event as unknown as Record<string, unknown>),
          run_id: (event as unknown as { run_id?: unknown }).run_id ?? rid,
          created_at: new Date().toISOString(),
          threadId,
        }
        return (await this.emitEvent(
          stamped as unknown as Record<string, unknown> & { threadId: string }
        )) as typeof event
      },
      streamMessage: (streamOpts = {}) => {
        if (!runId)
          throw new Error('streamMessage requires the run to be open; remove lazy or emit first')
        return this.streamMessage({
          threadId,
          runId,
          author: streamOpts.author ?? author,
          metadata: streamOpts.metadata,
          onFinalEvent: streamOpts.onFinalEvent,
        })
      },
      streamReasoning: (streamOpts = {}) => {
        if (!runId)
          throw new Error('streamReasoning requires the run to be open; remove lazy or emit first')
        return this.streamReasoning({
          threadId,
          runId,
          author: streamOpts.author ?? author,
          metadata: streamOpts.metadata,
          onFinalEvent: streamOpts.onFinalEvent,
        })
      },
    }

    try {
      const result = await callback(send)
      if (runId) await this.endRun(runId)
      return result
    } catch (err) {
      if (runId) {
        await this.endRun(runId, {
          error: {
            code: 'send_error',
            message: err instanceof Error ? err.message : String(err),
          },
        })
      }
      throw err
    }
  }

  connect(): Promise<void> {
    return this.socket.connect()
  }

  disconnect(): Promise<void> {
    return this.socket.disconnect()
  }

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
    await this.socket.disconnect()

    if (opts.url !== undefined) this.url = opts.url.replace(/\/$/, '')
    if (opts.path !== undefined) this.path = opts.path
    if (opts.socketPath !== undefined) this.socketPath = opts.socketPath
    if (opts.fetchImpl !== undefined) this.fetchImpl = opts.fetchImpl
    if (opts.identity !== undefined) this.identity = opts.identity
    if (opts.authenticate !== undefined) {
      this.authenticateFn = opts.authenticate
    } else if (opts.identity !== undefined && opts.identity !== null) {
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

    const { rest, socket } = this._buildTransports()
    this.rest = rest
    this.socket = socket

    await this.socket.connect()

    for (const entry of this.listeners) {
      this.socket.on(entry.event, entry.handler)
    }
  }

  on(event: string, handler: (data: unknown) => void): () => void {
    const entry: ListenerEntry = { event, handler }
    this.listeners.push(entry)
    this.socket.on(event, handler)
    return () => {
      const idx = this.listeners.indexOf(entry)
      if (idx !== -1) this.listeners.splice(idx, 1)

      const sock = this.socket.rawSocket
      if (sock) sock.off(event, handler)
    }
  }

  joinThread(
    threadId: string,
    since?: { createdAt: string; id: string }
  ): Promise<{ threadId: string; replayed: Event[]; replayTruncated: boolean }> {
    return this.socket.joinThread(threadId, since)
  }

  leaveThread(threadId: string): Promise<void> {
    return this.socket.leaveThread(threadId)
  }

  get rawSocket(): Socket | null {
    return this.socket.rawSocket
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
