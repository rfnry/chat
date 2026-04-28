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

import type { AssistantIdentity, MessageEvent, UserIdentity } from '@rfnry/chat-protocol'
import { ChatClient } from '../../src/client'

const me: AssistantIdentity = {
  role: 'assistant',
  id: 'a_me',
  name: 'Me',
  metadata: {},
}

const alice: UserIdentity = {
  role: 'user',
  id: 'u_alice',
  name: 'Alice',
  metadata: {},
}

function fakeFetchForRun(runId: string) {
  const now = new Date().toISOString()
  return vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        id: runId,
        thread_id: 't_1',
        actor: me,
        triggered_by: alice,
        status: 'running',
        started_at: now,
        metadata: {},
      }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    )
  )
}

describe('ChatClient.beginRun triggeredBy', () => {
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

  it('beginRun({}) sends no triggered_by_event_id', async () => {
    emitWithAck.mockResolvedValueOnce({ runId: 'run_1', status: 'running' })
    const client = new ChatClient({
      url: 'http://t',
      fetchImpl: fakeFetchForRun('run_1') as unknown as typeof fetch,
    })
    await client.connect()
    await client.beginRun('t_1')
    const call = emitWithAck.mock.calls.find((c) => c[0] === 'run:begin')!
    expect(call[1]).toEqual({ thread_id: 't_1' })
  })

  it('beginRun({ triggeredByEventId }) forwards as-is', async () => {
    emitWithAck.mockResolvedValueOnce({ runId: 'run_2', status: 'running' })
    const client = new ChatClient({
      url: 'http://t',
      fetchImpl: fakeFetchForRun('run_2') as unknown as typeof fetch,
    })
    await client.connect()
    await client.beginRun('t_1', { triggeredByEventId: 'evt_explicit' })
    const call = emitWithAck.mock.calls.find((c) => c[0] === 'run:begin')!
    expect(call[1].triggered_by_event_id).toBe('evt_explicit')
  })

  it('beginRun({ triggeredBy: Event }) extracts event.id', async () => {
    emitWithAck.mockResolvedValueOnce({ runId: 'run_3', status: 'running' })
    const client = new ChatClient({
      url: 'http://t',
      fetchImpl: fakeFetchForRun('run_3') as unknown as typeof fetch,
    })
    await client.connect()
    const event: MessageEvent = {
      type: 'message',
      id: 'evt_origin',
      thread_id: 't_1',
      author: alice,
      created_at: new Date().toISOString(),
      metadata: {},
      content: [{ type: 'text', text: 'hi' }],
      run_id: null,
      client_id: null,
      recipients: null,
    } as unknown as MessageEvent
    await client.beginRun('t_1', { triggeredBy: event })
    const call = emitWithAck.mock.calls.find((c) => c[0] === 'run:begin')!
    expect(call[1].triggered_by_event_id).toBe('evt_origin')
  })

  it('beginRun({ triggeredBy: Identity }) does NOT carry on the wire (Identity-only is documented limit)', async () => {
    emitWithAck.mockResolvedValueOnce({ runId: 'run_4', status: 'running' })
    const client = new ChatClient({
      url: 'http://t',
      fetchImpl: fakeFetchForRun('run_4') as unknown as typeof fetch,
    })
    await client.connect()
    await client.beginRun('t_1', { triggeredBy: alice })
    const call = emitWithAck.mock.calls.find((c) => c[0] === 'run:begin')!
    expect(call[1].triggered_by_event_id).toBeUndefined()
  })

  it('explicit triggeredByEventId wins over triggeredBy: Event', async () => {
    emitWithAck.mockResolvedValueOnce({ runId: 'run_5', status: 'running' })
    const client = new ChatClient({
      url: 'http://t',
      fetchImpl: fakeFetchForRun('run_5') as unknown as typeof fetch,
    })
    await client.connect()
    const event = {
      type: 'message',
      id: 'evt_origin',
      thread_id: 't_1',
      author: alice,
      created_at: new Date().toISOString(),
      metadata: {},
      content: [],
    } as unknown as MessageEvent
    await client.beginRun('t_1', { triggeredBy: event, triggeredByEventId: 'evt_explicit' })
    const call = emitWithAck.mock.calls.find((c) => c[0] === 'run:begin')!
    expect(call[1].triggered_by_event_id).toBe('evt_explicit')
  })
})
