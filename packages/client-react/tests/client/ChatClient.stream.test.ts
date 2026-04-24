import { beforeEach, describe, expect, it, vi } from 'vitest'

const emitWithAck = vi.fn()
const mockSocket = {
  on: vi.fn(),
  off: vi.fn(),
  once: vi.fn(),
  emit: vi.fn(),
  emitWithAck: vi.fn(),
  timeout: vi.fn(() => ({ emitWithAck })),
  disconnect: vi.fn(),
}

const mockIo = vi.fn(() => mockSocket)

vi.mock('socket.io-client', () => ({
  io: (...args: unknown[]) => mockIo(...(args as [])),
}))

import type { AssistantIdentity } from '@rfnry/chat-protocol'
import { ChatClient } from '../../src/client'

const me: AssistantIdentity = {
  role: 'assistant',
  id: 'a_me',
  name: 'Me',
  metadata: {},
}

describe('ChatClient stream + event emission', () => {
  beforeEach(() => {
    emitWithAck.mockReset()
    mockSocket.on.mockReset()
    mockSocket.off.mockReset()
    mockSocket.once.mockReset()
    mockSocket.emit.mockReset()
    mockSocket.emitWithAck.mockReset()
    mockSocket.timeout.mockClear()
    mockSocket.disconnect.mockReset()
    mockIo.mockClear()
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') queueMicrotask(() => cb())
    })
  })

  it('emitEvent calls event:send with camelCase→snake_case payload', async () => {
    const now = new Date().toISOString()
    emitWithAck.mockResolvedValue({
      event: {
        id: 'evt_out',
        thread_id: 't_1',
        type: 'reasoning',
        author: me,
        created_at: now,
        metadata: {},
        content: 'thinking',
      },
    })

    const client = new ChatClient({ url: 'http://localhost:8000' })
    await client.connect()
    const returned = await client.emitEvent({
      type: 'reasoning',
      threadId: 't_1',
      author: me,
      createdAt: now,
      content: 'thinking',
    })

    const call = emitWithAck.mock.calls.find((c) => c[0] === 'event:send')!
    expect(call[1].thread_id).toBe('t_1')
    const wire = call[1].event as Record<string, unknown>
    expect(wire.thread_id).toBe('t_1')
    expect(wire.created_at).toBe(now)
    expect((wire.author as { id: string }).id).toBe('a_me')
    expect(returned.type).toBe('reasoning')
  })

  it('beginRun emits run:begin and resolves via REST getRun', async () => {
    const now = new Date().toISOString()
    emitWithAck.mockResolvedValueOnce({ run_id: 'run_42', status: 'running' })

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 'run_42',
          thread_id: 't_1',
          actor: me,
          triggered_by: { role: 'user', id: 'u1', name: 'U', metadata: {} },
          status: 'running',
          started_at: now,
          metadata: {},
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      )
    )
    const client = new ChatClient({
      url: 'http://localhost:8000',
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
    await client.connect()
    const run = await client.beginRun('t_1', { triggeredByEventId: 'evt_0' })

    expect(emitWithAck).toHaveBeenCalledWith('run:begin', {
      thread_id: 't_1',
      triggered_by_event_id: 'evt_0',
    })
    expect(run.id).toBe('run_42')
  })

  it('streamMessage lifecycle sends start, delta, end frames', async () => {
    emitWithAck.mockResolvedValue({ ok: true })

    const client = new ChatClient({ url: 'http://localhost:8000' })
    await client.connect()

    const stream = client.streamMessage({
      threadId: 't_1',
      runId: 'run_1',
      author: me,
    })
    await stream.start()
    await stream.write('hello ')
    await stream.write('world')
    const final = await stream.end()

    const callNames = emitWithAck.mock.calls.map((c) => c[0])
    expect(callNames).toContain('stream:start')
    expect(callNames.filter((n) => n === 'stream:delta')).toHaveLength(2)
    expect(callNames).toContain('stream:end')

    expect(final).not.toBeNull()
    if (final && final.type === 'message') {
      expect(final.content[0]!.type).toBe('text')
    }
  })

  it('stream.end with error does not produce a final event', async () => {
    emitWithAck.mockResolvedValue({ ok: true })

    const client = new ChatClient({ url: 'http://localhost:8000' })
    await client.connect()
    const stream = client.streamMessage({ threadId: 't_1', runId: 'run_1', author: me })
    await stream.start()
    await stream.write('partial')
    const final = await stream.end({ code: 'boom', message: 'failed' })

    const endCall = emitWithAck.mock.calls.find((c) => c[0] === 'stream:end')!
    expect(endCall[1].error).toEqual({ code: 'boom', message: 'failed' })
    expect(final).toBeNull()
  })
})
