import type { Identity, MessageEvent, ReasoningEvent } from '@rfnry/chat-protocol'
import type { SocketTransport } from './transport/socket'

export type StreamOptions = {
  socket: SocketTransport
  threadId: string
  runId: string
  author: Identity
  targetType: 'message' | 'reasoning'
  metadata?: Record<string, unknown>
  onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
}

export class ChatStream {
  readonly eventId: string
  private readonly socket: SocketTransport
  private readonly threadId: string
  private readonly runId: string
  private readonly author: Identity
  private readonly targetType: 'message' | 'reasoning'
  private readonly metadata: Record<string, unknown>
  private readonly onFinalEvent?: StreamOptions['onFinalEvent']
  private buffer: string[] = []
  private started = false
  private ended = false

  constructor(opts: StreamOptions) {
    this.socket = opts.socket
    this.threadId = opts.threadId
    this.runId = opts.runId
    this.author = opts.author
    this.targetType = opts.targetType
    this.metadata = opts.metadata ?? {}
    this.onFinalEvent = opts.onFinalEvent
    this.eventId = `evt_${randomHex(8)}`
  }

  async start(): Promise<void> {
    if (this.started) throw new Error('stream already started')
    await this.socket.sendStreamStart({
      eventId: this.eventId,
      threadId: this.threadId,
      runId: this.runId,
      targetType: this.targetType,
      author: authorWire(this.author),
    })
    this.started = true
  }

  async write(text: string): Promise<void> {
    if (!this.started) throw new Error('stream.write called before start')
    if (this.ended) throw new Error('stream.write called after end')
    if (!text) return
    this.buffer.push(text)
    await this.socket.sendStreamDelta({
      eventId: this.eventId,
      threadId: this.threadId,
      text,
    })
  }

  async end(error?: {
    code: string
    message: string
  }): Promise<MessageEvent | ReasoningEvent | null> {
    if (this.ended) return null
    this.ended = true
    await this.socket.sendStreamEnd({
      eventId: this.eventId,
      threadId: this.threadId,
      error: error ?? null,
    })
    if (error) return null

    const content = this.buffer.join('')
    const createdAt = new Date().toISOString()
    let final: MessageEvent | ReasoningEvent
    if (this.targetType === 'message') {
      final = {
        id: this.eventId,
        threadId: this.threadId,
        runId: this.runId,
        author: this.author,
        createdAt,
        metadata: this.metadata,
        recipients: null,
        type: 'message',
        content: [{ type: 'text', text: content }],
      }
    } else {
      final = {
        id: this.eventId,
        threadId: this.threadId,
        runId: this.runId,
        author: this.author,
        createdAt,
        metadata: this.metadata,
        recipients: null,
        type: 'reasoning',
        content,
      }
    }
    if (this.onFinalEvent) {
      await this.onFinalEvent(final)
    }
    return final
  }
}

function randomHex(bytes: number): string {
  const arr = new Uint8Array(bytes)
  crypto.getRandomValues(arr)
  return Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('')
}

function authorWire(identity: Identity): Record<string, unknown> {
  return {
    role: identity.role,
    id: identity.id,
    name: identity.name,
    metadata: identity.metadata,
  }
}
