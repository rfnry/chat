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

import { ChatClient } from '../../src/client'

const ISO = '2026-04-21T00:00:00Z'

function threadResponse(id: string) {
  return {
    id,
    tenant: {},
    metadata: {},
    created_at: ISO,
    updated_at: ISO,
  }
}

function memberResponse(threadId: string, identityId: string) {
  return {
    thread_id: threadId,
    identity_id: identityId,
    identity: { role: 'user', id: identityId, name: identityId, metadata: {} },
    role: 'member',
    added_at: ISO,
    added_by: { role: 'assistant', id: 'a_me', name: 'Me', metadata: {} },
  }
}

function messageEventResponse(threadId: string, clientId: string) {
  return {
    id: 'evt_sent',
    thread_id: threadId,
    type: 'message',
    author: { role: 'assistant', id: 'a_me', name: 'Me', metadata: {} },
    created_at: ISO,
    metadata: {},
    content: [{ type: 'text', text: 'ping' }],
    client_id: clientId,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('ChatClient.openThreadWith', () => {
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

  it('creates thread, adds invite, joins, and sends message in order with right args', async () => {
    const order: string[] = []

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = (init?.method ?? 'GET').toUpperCase()

      if (method === 'POST' && url.endsWith('/chat/threads')) {
        order.push('createThread')
        return jsonResponse(threadResponse('th_new'), 201)
      }
      if (method === 'POST' && url.endsWith('/chat/threads/th_new/members')) {
        order.push('addMember')
        return jsonResponse(memberResponse('th_new', 'u_alice'), 201)
      }
      if (method === 'POST' && url.endsWith('/chat/threads/th_new/messages')) {
        order.push('sendMessage')
        const body = JSON.parse(init?.body as string) as Record<string, unknown>
        return jsonResponse(messageEventResponse('th_new', body.client_id as string), 201)
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    })

    emitWithAck.mockImplementation(async (event: string) => {
      if (event === 'thread:join') {
        order.push('joinThread')
        return { thread_id: 'th_new', replayed: [], replay_truncated: false }
      }
      throw new Error(`unexpected emit: ${event}`)
    })

    const client = new ChatClient({
      url: 'http://chat.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
    await client.connect()

    const invite = {
      role: 'user' as const,
      id: 'u_alice',
      name: 'Alice',
      metadata: {},
    }

    const result = await client.openThreadWith({
      message: [{ type: 'text', text: 'ping' }],
      invite,
      clientId: 'c_test',
    })

    expect(result.thread.id).toBe('th_new')
    expect(result.event.id).toBe('evt_sent')

    expect(order).toEqual(['createThread', 'addMember', 'joinThread', 'sendMessage'])

    const sendCall = fetchMock.mock.calls.find(([u, i]) => {
      const url = typeof u === 'string' ? u : (u as URL | Request).toString()
      return url.endsWith('/chat/threads/th_new/messages') && (i as RequestInit).method === 'POST'
    })
    expect(sendCall).toBeDefined()
    const body = JSON.parse((sendCall![1] as RequestInit).body as string) as Record<string, unknown>
    expect(body.recipients).toEqual(['u_alice'])
    expect(body.client_id).toBe('c_test')
    expect(body.content).toEqual([{ type: 'text', text: 'ping' }])

    expect(emitWithAck).toHaveBeenCalledWith('thread:join', {
      thread_id: 'th_new',
    })
  })

  it('reuses existing thread (GET not POST) when threadId is supplied and skips add_member when no invite', async () => {
    const methodsHit: string[] = []

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = (init?.method ?? 'GET').toUpperCase()
      methodsHit.push(`${method} ${url}`)

      if (method === 'GET' && url.endsWith('/chat/threads/th_existing')) {
        return jsonResponse(threadResponse('th_existing'), 200)
      }
      if (method === 'POST' && url.endsWith('/chat/threads/th_existing/messages')) {
        const body = JSON.parse(init?.body as string) as Record<string, unknown>
        return jsonResponse(messageEventResponse('th_existing', body.client_id as string), 201)
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    })

    emitWithAck.mockResolvedValue({
      thread_id: 'th_existing',
      replayed: [],
      replay_truncated: false,
    })

    const client = new ChatClient({
      url: 'http://chat.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
    await client.connect()

    const result = await client.openThreadWith({
      message: [{ type: 'text', text: 'ping' }],
      threadId: 'th_existing',
      clientId: 'c_test',
    })

    expect(result.thread.id).toBe('th_existing')

    expect(methodsHit.filter((s) => s.startsWith('POST') && s.endsWith('/threads'))).toHaveLength(0)
    expect(methodsHit.filter((s) => s.includes('/members'))).toHaveLength(0)

    const sendCall = fetchMock.mock.calls.find(([u, i]) => {
      const url = typeof u === 'string' ? u : (u as URL | Request).toString()
      return (
        url.endsWith('/chat/threads/th_existing/messages') && (i as RequestInit).method === 'POST'
      )
    })
    const body = JSON.parse((sendCall![1] as RequestInit).body as string) as Record<string, unknown>
    expect(body.recipients).toBeNull()
  })
})
