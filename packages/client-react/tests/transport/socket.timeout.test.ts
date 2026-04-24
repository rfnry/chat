import { beforeEach, describe, expect, it, vi } from 'vitest'

const emitWithAck = vi.fn()
const timeout = vi.fn(() => ({ emitWithAck }))
const mockSocket = {
  on: vi.fn(),
  off: vi.fn(),
  once: vi.fn(),
  disconnect: vi.fn(),
  emitWithAck: vi.fn(),
  timeout,
}
const mockIo = vi.fn(() => mockSocket)

vi.mock('socket.io-client', () => ({
  io: (...args: unknown[]) => mockIo(...(args as [])),
}))

import { SocketTransport } from '../../src/transport/socket'

async function connectedTransport(ackMs?: number) {
  mockSocket.once.mockImplementation((event: string, cb: () => void) => {
    if (event === 'connect') queueMicrotask(() => cb())
  })
  const t = new SocketTransport({
    baseUrl: 'http://chat.test',
    ...(ackMs !== undefined ? { ackTimeoutMs: ackMs } : {}),
  })
  await t.connect()
  return t
}

describe('SocketTransport emitWithAck timeouts', () => {
  beforeEach(() => {
    emitWithAck.mockReset().mockResolvedValue({})
    timeout.mockClear()
    mockSocket.on.mockReset()
    mockSocket.off.mockReset()
    mockSocket.once.mockReset()
    mockSocket.disconnect.mockReset()
    mockSocket.emitWithAck.mockReset()
    mockIo.mockClear()
  })

  it('passes a 15s default timeout to every emitWithAck', async () => {
    const t = await connectedTransport()
    emitWithAck.mockResolvedValue({
      thread_id: 'th_x',
      replayed: [],
      replay_truncated: false,
    })
    await t.joinThread('th_x')
    expect(timeout).toHaveBeenCalledWith(15_000)
  })

  it('honors a custom ackTimeoutMs', async () => {
    const t = await connectedTransport(3_000)
    emitWithAck.mockResolvedValue({})
    await t.leaveThread('th_x')
    expect(timeout).toHaveBeenCalledWith(3_000)
  })

  it('wraps stream:start with the same timeout', async () => {
    const t = await connectedTransport(7_500)
    emitWithAck.mockResolvedValue({ ok: true })
    await t.sendStreamStart({
      eventId: 'evt_1',
      threadId: 'th_x',
      runId: 'run_y',
      targetType: 'message',
      author: { id: 'u_alice', type: 'user' },
    })
    expect(timeout).toHaveBeenCalledWith(7_500)
  })

  it('wraps stream:end with the same timeout', async () => {
    const t = await connectedTransport(9_999)
    emitWithAck.mockResolvedValue({ ok: true })
    await t.sendStreamEnd({ eventId: 'evt_1', threadId: 'th_x' })
    expect(timeout).toHaveBeenCalledWith(9_999)
  })
})
