import type { AssistantIdentity, MessageEvent } from '@rfnry/chat-protocol'
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

vi.mock('socket.io-client', () => ({
  io: vi.fn(() => mockSocket),
}))

import { ChatClient } from '../../src/client'

const ME: AssistantIdentity = { role: 'assistant', id: 'a_me', name: 'Me', metadata: {} }
const ISO = '2026-04-28T00:00:00Z'

function makeRunResponse(runId: string) {
  return new Response(
    JSON.stringify({
      id: runId,
      thread_id: 't_1',
      actor: ME,
      triggered_by: ME,
      status: 'running',
      started_at: ISO,
      metadata: {},
    }),
    { status: 200, headers: { 'content-type': 'application/json' } }
  )
}

function makeClient(): ChatClient {
  const fetchMock = vi.fn(async () => makeRunResponse('run_x'))
  return new ChatClient({
    url: 'http://t',
    identity: ME,
    fetchImpl: fetchMock as unknown as typeof fetch,
  })
}

describe('ChatClient.withRun', () => {
  beforeEach(() => {
    emitWithAck.mockReset()
    mockSocket.on.mockReset()
    mockSocket.off.mockReset()
    mockSocket.once.mockReset()
    mockSocket.emit.mockReset()
    mockSocket.emitWithAck.mockReset()
    mockSocket.timeout.mockClear()
    mockSocket.disconnect.mockReset()
    mockSocket.once.mockImplementation((event: string, cb: () => void) => {
      if (event === 'connect') queueMicrotask(() => cb())
    })
  })

  it('opens a Run on entry and closes it on return (eager mode)', async () => {
    emitWithAck.mockImplementation(async (event: string) => {
      if (event === 'run:begin') return { runId: 'run_1', status: 'running' }
      if (event === 'run:end') return { runId: 'run_1', status: 'completed' }
      throw new Error(`unexpected: ${event}`)
    })
    const client = makeClient()
    await client.connect()

    await client.withRun('t_1', async () => {})

    const beginCall = emitWithAck.mock.calls.find((c) => c[0] === 'run:begin')
    const endCall = emitWithAck.mock.calls.find((c) => c[0] === 'run:end')
    expect(beginCall).toBeDefined()
    expect(endCall).toBeDefined()
  })

  it('multi-emit shares one Run id', async () => {
    let beginCount = 0
    emitWithAck.mockImplementation(async (event: string) => {
      if (event === 'run:begin') {
        beginCount++
        return { runId: 'run_2', status: 'running' }
      }
      if (event === 'run:end') return { runId: 'run_2', status: 'completed' }
      if (event === 'event:send') {
        return {
          event: {
            id: 'evt_x',
            thread_id: 't_1',
            type: 'message',
            author: ME,
            created_at: ISO,
            metadata: {},
            content: [{ type: 'text', text: 'hi' }],
            run_id: 'run_2',
          },
        }
      }
      throw new Error(`unexpected: ${event}`)
    })
    const client = makeClient()
    await client.connect()

    await client.withRun('t_1', async (send) => {
      await send.message([{ type: 'text', text: 'one' }])
      await send.message([{ type: 'text', text: 'two' }])
    })

    expect(beginCount).toBe(1)
  })

  it('exception path closes Run with error code "send_error"', async () => {
    let endError: Record<string, unknown> | null = null
    emitWithAck.mockImplementation(async (event: string, payload: unknown) => {
      if (event === 'run:begin') return { runId: 'run_3', status: 'running' }
      if (event === 'run:end') {
        const p = payload as { run_id: string; error?: Record<string, unknown> }
        endError = p.error ?? null
        return { runId: 'run_3', status: 'failed' }
      }
      throw new Error(`unexpected: ${event}`)
    })
    const client = makeClient()
    await client.connect()

    await expect(
      client.withRun('t_1', async () => {
        throw new Error('boom')
      })
    ).rejects.toThrow('boom')

    expect(endError).not.toBeNull()
    expect((endError as unknown as Record<string, unknown>).code).toBe('send_error')
  })

  it('lazy: true skips run open if no emit happens', async () => {
    let beginCount = 0
    emitWithAck.mockImplementation(async (event: string) => {
      if (event === 'run:begin') {
        beginCount++
        return { runId: 'run_4', status: 'running' }
      }
      if (event === 'run:end') return { runId: 'run_4', status: 'completed' }
      throw new Error(`unexpected: ${event}`)
    })
    const client = makeClient()
    await client.connect()

    await client.withRun('t_1', async () => {}, { lazy: true })

    expect(beginCount).toBe(0)
  })

  it('lazy: true opens run on first emit', async () => {
    let beginCount = 0
    emitWithAck.mockImplementation(async (event: string) => {
      if (event === 'run:begin') {
        beginCount++
        return { runId: 'run_5', status: 'running' }
      }
      if (event === 'run:end') return { runId: 'run_5', status: 'completed' }
      if (event === 'event:send') {
        return {
          event: {
            id: 'evt_x',
            thread_id: 't_1',
            type: 'message',
            author: ME,
            created_at: ISO,
            metadata: {},
            content: [{ type: 'text', text: 'hi' }],
            run_id: 'run_5',
          },
        }
      }
      throw new Error(`unexpected: ${event}`)
    })
    const client = makeClient()
    await client.connect()

    await client.withRun(
      't_1',
      async (send) => {
        await send.message([{ type: 'text', text: 'late' }])
      },
      { lazy: true }
    )

    expect(beginCount).toBe(1)
  })

  it('triggeredBy: Event extracts event.id for begin_run', async () => {
    let beginPayload: Record<string, unknown> | null = null
    emitWithAck.mockImplementation(async (event: string, payload: unknown) => {
      if (event === 'run:begin') {
        beginPayload = payload as Record<string, unknown>
        return { runId: 'run_6', status: 'running' }
      }
      if (event === 'run:end') return { runId: 'run_6', status: 'completed' }
      throw new Error(`unexpected: ${event}`)
    })
    const client = makeClient()
    await client.connect()
    const triggering = {
      type: 'message',
      id: 'evt_origin',
      thread_id: 't_1',
      author: ME,
      created_at: ISO,
      metadata: {},
      content: [],
    } as unknown as MessageEvent

    await client.withRun('t_1', async () => {}, { triggeredBy: triggering })

    expect(beginPayload).not.toBeNull()
    expect((beginPayload as unknown as Record<string, unknown>).triggered_by_event_id).toBe(
      'evt_origin'
    )
  })

  it('idempotencyKey passes through to begin_run', async () => {
    let beginPayload: Record<string, unknown> | null = null
    emitWithAck.mockImplementation(async (event: string, payload: unknown) => {
      if (event === 'run:begin') {
        beginPayload = payload as Record<string, unknown>
        return { runId: 'run_7', status: 'running' }
      }
      if (event === 'run:end') return { runId: 'run_7', status: 'completed' }
      throw new Error(`unexpected: ${event}`)
    })
    const client = makeClient()
    await client.connect()

    await client.withRun('t_1', async () => {}, { idempotencyKey: 'op_xyz' })

    expect(beginPayload).not.toBeNull()
    expect((beginPayload as unknown as Record<string, unknown>).idempotency_key).toBe('op_xyz')
  })

  it('emitted events carry the run_id', async () => {
    let lastEmittedEvent: Record<string, unknown> | null = null
    emitWithAck.mockImplementation(async (event: string, payload: unknown) => {
      if (event === 'run:begin') return { runId: 'run_8', status: 'running' }
      if (event === 'run:end') return { runId: 'run_8', status: 'completed' }
      if (event === 'event:send') {
        const p = payload as { event: Record<string, unknown> }
        lastEmittedEvent = p.event
        return {
          event: {
            id: 'evt_z',
            thread_id: 't_1',
            type: 'message',
            author: ME,
            created_at: ISO,
            metadata: {},
            content: [{ type: 'text', text: 'hi' }],
            run_id: 'run_8',
          },
        }
      }
      throw new Error(`unexpected: ${event}`)
    })
    const client = makeClient()
    await client.connect()

    await client.withRun('t_1', async (send) => {
      await send.message([{ type: 'text', text: 'hi' }])
    })

    expect(lastEmittedEvent).not.toBeNull()
    expect((lastEmittedEvent as unknown as Record<string, unknown>).run_id).toBe('run_x')
  })
})
