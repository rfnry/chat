import { beforeEach, describe, expect, it, vi } from 'vitest'

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

describe('ChatClient.reconnect', () => {
  beforeEach(() => {
    mockSocket.on.mockReset()
    mockSocket.off.mockReset()
    mockSocket.once.mockReset()
    mockSocket.emit.mockReset()
    mockSocket.emitWithAck.mockReset()
    mockSocket.disconnect.mockReset()
    mockIo.mockClear()
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') queueMicrotask(() => cb())
    })
  })

  it('replays registered listeners onto the new socket', async () => {
    const client = new ChatClient({ url: 'http://old.test' })
    await client.connect()

    const handler = vi.fn()
    client.on('event', handler)
    expect(mockSocket.on).toHaveBeenCalledWith('event', handler)

    // Track how many io() calls have happened; reset mock call history so we
    // can assert the reconnect path registers again on the new socket.
    mockSocket.on.mockClear()
    mockSocket.disconnect.mockClear()
    mockIo.mockClear()

    await client.reconnect({ url: 'http://new.test' })

    // Old socket was torn down, new socket was built with new url.
    expect(mockSocket.disconnect).toHaveBeenCalled()
    expect(mockIo).toHaveBeenCalledWith(
      'http://new.test',
      expect.objectContaining({ transports: ['websocket'] })
    )

    // Registered listener re-attached to the (new) socket without caller
    // re-registering.
    expect(mockSocket.on).toHaveBeenCalledWith('event', handler)

    // Find the latest handler registered against 'event' and feed it — it
    // should be the same handler function we registered.
    const eventCalls = mockSocket.on.mock.calls.filter((c) => c[0] === 'event')
    expect(eventCalls.length).toBeGreaterThan(0)
    const attached = eventCalls[eventCalls.length - 1]![1] as (data: unknown) => void
    const payload = { id: 'evt_after', type: 'message' }
    attached(payload)
    expect(handler).toHaveBeenCalledWith(payload)
  })

  it('keeps current values for options not supplied', async () => {
    const client = new ChatClient({
      url: 'http://old.test',
      path: '/custom',
      socketPath: '/custom/ws',
    })
    await client.connect()

    mockIo.mockClear()
    await client.reconnect({}) // no changes

    expect(mockIo).toHaveBeenCalledTimes(1)
    expect(mockIo).toHaveBeenCalledWith(
      'http://old.test',
      expect.objectContaining({ path: '/custom/ws' })
    )
    expect(client.url).toBe('http://old.test')
    expect(client.path).toBe('/custom')
    expect(client.socketPath).toBe('/custom/ws')
  })

  it('updates identity when supplied and exposes it via the field', async () => {
    const client = new ChatClient({ url: 'http://old.test' })
    await client.connect()

    expect(client.identity).toBeNull()

    const nextIdentity = { role: 'user' as const, id: 'u_1', name: 'U', metadata: {} }
    await client.reconnect({ identity: nextIdentity })
    expect(client.identity).toEqual(nextIdentity)
  })

  it('disposer returned by on() unregisters the listener so it is NOT replayed', async () => {
    const client = new ChatClient({ url: 'http://old.test' })
    await client.connect()

    const handler = vi.fn()
    const off = client.on('event', handler)
    off()

    mockSocket.on.mockClear()
    await client.reconnect({ url: 'http://new.test' })

    // No 'event' registration should happen after reconnect because the
    // disposer removed the handler from the registry.
    const eventCalls = mockSocket.on.mock.calls.filter((c) => c[0] === 'event')
    expect(eventCalls).toEqual([])
  })
})
