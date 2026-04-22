import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SocketTransportError } from '../../src/errors'

const mockSocket = {
  on: vi.fn(),
  off: vi.fn(),
  once: vi.fn(),
  emit: vi.fn(),
  emitWithAck: vi.fn(),
  disconnect: vi.fn(),
}

const mockIo = vi.fn(() => mockSocket)

vi.mock('socket.io-client', () => ({
  io: (...args: unknown[]) => mockIo(...(args as [])),
}))

import { ChatClient } from '../../src/client'

describe('ChatClient socket', () => {
  beforeEach(() => {
    mockSocket.on.mockReset()
    mockSocket.off.mockReset()
    mockSocket.once.mockReset()
    mockSocket.emit.mockReset()
    mockSocket.emitWithAck.mockReset()
    mockSocket.disconnect.mockReset()
    mockIo.mockClear()
  })

  it('connect resolves on connect event', async () => {
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') {
        queueMicrotask(() => cb())
      }
    })
    const client = new ChatClient({ url: 'http://localhost:8000' })
    await client.connect()
    expect(mockIo).toHaveBeenCalledWith(
      'http://localhost:8000',
      expect.objectContaining({ transports: ['websocket'] })
    )
  })

  it('joinThread emits thread:join with snake_case payload and parses response', async () => {
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') queueMicrotask(() => cb())
    })
    mockSocket.emitWithAck.mockResolvedValue({
      thread_id: 'th_1',
      replayed: [
        {
          id: 'evt_1',
          thread_id: 'th_1',
          type: 'message',
          author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
          created_at: '2026-04-10T00:00:00Z',
          metadata: {},
          content: [{ type: 'text', text: 'hi' }],
        },
      ],
      replay_truncated: false,
    })

    const client = new ChatClient({ url: 'http://localhost:8000' })
    await client.connect()
    const result = await client.joinThread('th_1', {
      createdAt: '2026-04-10T00:00:00Z',
      id: 'evt_0',
    })

    expect(mockSocket.emitWithAck).toHaveBeenCalledWith('thread:join', {
      thread_id: 'th_1',
      since: { created_at: '2026-04-10T00:00:00Z', id: 'evt_0' },
    })
    expect(result.threadId).toBe('th_1')
    expect(result.replayed).toHaveLength(1)
    expect(result.replayed[0]!.type).toBe('message')
  })

  it('joinThread throws on error response', async () => {
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') queueMicrotask(() => cb())
    })
    mockSocket.emitWithAck.mockResolvedValue({
      error: { code: 'forbidden', message: 'not a member' },
    })

    const client = new ChatClient({ url: 'http://localhost:8000' })
    await client.connect()
    await expect(client.joinThread('th_1')).rejects.toThrow('forbidden')
  })

  it('throws SocketTransportError (NOT ChatHttpError) on socket-level ack errors', async () => {
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') queueMicrotask(() => cb())
    })
    mockSocket.emitWithAck.mockResolvedValue({
      error: { code: 'forbidden', message: 'not a member' },
    })

    const client = new ChatClient({ url: 'http://localhost:8000' })
    await client.connect()

    let caught: unknown = null
    try {
      await client.joinThread('th_1')
    } catch (err) {
      caught = err
    }

    expect(caught).toBeInstanceOf(SocketTransportError)
    const err = caught as SocketTransportError
    expect(err.name).toBe('SocketTransportError')
    expect(err.code).toBe('forbidden')
    expect(err.message).toBe('forbidden: not a member')
    // Regression guard: socket errors must NOT masquerade as HTTP 0.
    expect((err as unknown as { status?: number }).status).toBeUndefined()
  })

  it('on returns unsubscribe function', async () => {
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') queueMicrotask(() => cb())
    })
    const client = new ChatClient({ url: 'http://localhost:8000' })
    await client.connect()
    const handler = vi.fn()
    const off = client.on('event', handler)
    expect(mockSocket.on).toHaveBeenCalledWith('event', handler)
    off()
    expect(mockSocket.off).toHaveBeenCalledWith('event', handler)
  })
})
