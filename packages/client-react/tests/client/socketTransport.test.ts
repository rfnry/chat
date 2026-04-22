import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockSocket = {
  on: vi.fn(),
  off: vi.fn(),
  once: vi.fn(),
  disconnect: vi.fn(),
}

const ioMock = vi.fn(() => mockSocket)

vi.mock('socket.io-client', () => ({
  io: (...args: unknown[]) => ioMock(...(args as [])),
}))

import { SocketTransport } from '../../src/transport/socket'

describe('SocketTransport.connect', () => {
  beforeEach(() => {
    mockSocket.on.mockReset()
    mockSocket.off.mockReset()
    mockSocket.once.mockReset()
    mockSocket.disconnect.mockReset()
    ioMock.mockClear()
  })

  it('passes reconnectionDelayMax to socket.io-client to spread reconnect herds', async () => {
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') queueMicrotask(() => cb())
    })
    const t = new SocketTransport({ baseUrl: 'http://chat.test' })
    await t.connect()
    expect(ioMock).toHaveBeenCalledTimes(1)
    const call = ioMock.mock.calls[0] as unknown as [string, Record<string, unknown>]
    const opts = call[1]
    expect(opts.reconnectionDelayMax).toBeGreaterThanOrEqual(30_000)
  })
})
