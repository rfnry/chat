import type { Event } from '@rfnry/chat-protocol'
import { toEvent } from '@rfnry/chat-protocol'
import { io, type Socket } from 'socket.io-client'
import { ChatHttpError } from '../errors'

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
