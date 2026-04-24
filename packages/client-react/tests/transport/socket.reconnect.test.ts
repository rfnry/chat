import { beforeEach, describe, expect, it, vi } from 'vitest'

const handlers: Record<string, Array<(data?: unknown) => void>> = {}

function pushHandler(event: string, cb: (data?: unknown) => void) {
  if (!handlers[event]) handlers[event] = []
  handlers[event].push(cb)
}

const mockSocket = {
  on: vi.fn((event: string, cb: (data?: unknown) => void) => {
    pushHandler(event, cb)
  }),
  off: vi.fn(),
  once: vi.fn((event: string, cb: () => void) => {
    if (event === 'connect') queueMicrotask(() => cb())
  }),
  disconnect: vi.fn(),
  emitWithAck: vi.fn(),
  timeout: vi.fn(() => ({ emitWithAck: vi.fn() })),
}
const mockIo = vi.fn(() => mockSocket)
vi.mock('socket.io-client', () => ({
  io: (...args: unknown[]) => mockIo(...(args as [])),
}))

import { SocketTransport } from '../../src/transport/socket'

describe('SocketTransport reconnect bounds', () => {
  beforeEach(() => {
    for (const k of Object.keys(handlers)) {
      handlers[k] = []
    }
    mockSocket.on.mockReset().mockImplementation((event: string, cb: (data?: unknown) => void) => {
      pushHandler(event, cb)
    })
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') queueMicrotask(() => cb())
    })
    mockIo.mockClear()
  })

  it('passes a bounded reconnectionAttempts by default', async () => {
    const t = new SocketTransport({ baseUrl: 'http://chat.test' })
    await t.connect()
    const [, opts] = mockIo.mock.calls[0] as unknown as [string, Record<string, unknown>]
    expect(opts.reconnectionAttempts).toBeLessThan(Number.POSITIVE_INFINITY)
    expect(opts.reconnectionAttempts).toBeGreaterThanOrEqual(5)
  })

  it('respects caller-supplied reconnectionAttempts', async () => {
    const t = new SocketTransport({ baseUrl: 'http://chat.test', reconnectionAttempts: 3 })
    await t.connect()
    const [, opts] = mockIo.mock.calls[0] as unknown as [string, Record<string, unknown>]
    expect(opts.reconnectionAttempts).toBe(3)
  })

  it('invokes onReconnectFailed when the socket emits reconnect_failed', async () => {
    const onReconnectFailed = vi.fn()
    const t = new SocketTransport({ baseUrl: 'http://chat.test', onReconnectFailed })
    await t.connect()
    // simulate socket.io firing reconnect_failed
    for (const cb of handlers['reconnect_failed'] ?? []) cb()
    expect(onReconnectFailed).toHaveBeenCalledTimes(1)
  })
})
