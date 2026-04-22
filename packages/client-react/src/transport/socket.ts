import type { Event } from '@rfnry/chat-protocol'
import { toEvent } from '@rfnry/chat-protocol'
import { io, type Socket } from 'socket.io-client'
import { SocketTransportError } from '../errors'

export type SocketAuthPayload = {
  headers?: Record<string, string>
  auth?: Record<string, unknown>
}

export type SocketTransportOptions = {
  baseUrl: string
  socketPath?: string
  authenticate?: () => Promise<SocketAuthPayload>
}

export class SocketTransport {
  readonly baseUrl: string
  readonly socketPath: string
  private readonly authenticate?: SocketTransportOptions['authenticate']
  private socket: Socket | null = null

  constructor(opts: SocketTransportOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '')
    this.socketPath = opts.socketPath ?? '/chat/ws'
    this.authenticate = opts.authenticate
  }

  async connect(): Promise<void> {
    const auth = this.authenticate ? ((await this.authenticate()).auth ?? {}) : {}
    const socket = io(this.baseUrl, {
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
      throw new SocketTransportError(response.error.code, response.error.message)
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

  async sendEvent(threadId: string, event: Record<string, unknown>): Promise<Event> {
    if (!this.socket) throw new Error('not connected')
    const reply = (await this.socket.emitWithAck('event:send', {
      thread_id: threadId,
      event,
    })) as { event?: unknown; error?: { code: string; message: string } }
    if (reply.error) {
      throw new SocketTransportError(reply.error.code, reply.error.message)
    }
    return toEvent(reply.event as never)
  }

  async beginRun(
    threadId: string,
    opts: { triggeredByEventId?: string; idempotencyKey?: string } = {}
  ): Promise<{ runId: string; status: string }> {
    if (!this.socket) throw new Error('not connected')
    const payload: Record<string, unknown> = { thread_id: threadId }
    if (opts.triggeredByEventId) payload.triggered_by_event_id = opts.triggeredByEventId
    if (opts.idempotencyKey) payload.idempotency_key = opts.idempotencyKey
    const reply = (await this.socket.emitWithAck('run:begin', payload)) as {
      run_id?: string
      status?: string
      error?: { code: string; message: string }
    }
    if (reply.error) {
      throw new SocketTransportError(reply.error.code, reply.error.message)
    }
    return { runId: reply.run_id!, status: reply.status! }
  }

  async endRun(
    runId: string,
    opts: { error?: { code: string; message: string } } = {}
  ): Promise<{ runId: string; status: string }> {
    if (!this.socket) throw new Error('not connected')
    const payload: Record<string, unknown> = { run_id: runId }
    if (opts.error) payload.error = opts.error
    const reply = (await this.socket.emitWithAck('run:end', payload)) as {
      run_id?: string
      status?: string
      error?: { code: string; message: string }
    }
    if (reply.error) {
      throw new SocketTransportError(reply.error.code, reply.error.message)
    }
    return { runId: reply.run_id!, status: reply.status! }
  }

  async sendStreamStart(frame: {
    eventId: string
    threadId: string
    runId: string
    targetType: 'message' | 'reasoning'
    author: Record<string, unknown>
  }): Promise<void> {
    await this._sendStreamFrame('stream:start', {
      event_id: frame.eventId,
      thread_id: frame.threadId,
      run_id: frame.runId,
      target_type: frame.targetType,
      author: frame.author,
    })
  }

  async sendStreamDelta(frame: { eventId: string; threadId: string; text: string }): Promise<void> {
    await this._sendStreamFrame('stream:delta', {
      event_id: frame.eventId,
      thread_id: frame.threadId,
      text: frame.text,
    })
  }

  async sendStreamEnd(frame: {
    eventId: string
    threadId: string
    error?: { code: string; message: string } | null
  }): Promise<void> {
    const payload: Record<string, unknown> = {
      event_id: frame.eventId,
      thread_id: frame.threadId,
    }
    if (frame.error) payload.error = frame.error
    await this._sendStreamFrame('stream:end', payload)
  }

  private async _sendStreamFrame(event: string, payload: Record<string, unknown>): Promise<void> {
    if (!this.socket) throw new Error('not connected')
    const reply = (await this.socket.emitWithAck(event, payload)) as {
      ok?: boolean
      error?: { code: string; message: string }
    }
    if (reply.error) {
      throw new SocketTransportError(reply.error.code, reply.error.message)
    }
  }

  get rawSocket(): Socket | null {
    return this.socket
  }
}
