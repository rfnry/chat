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

const ISO = '2026-04-28T00:00:00Z'

const ALICE = { role: 'user' as const, id: 'u_alice', name: 'Alice', metadata: {} }

function threadResponse(id: string) {
  return { id, tenant: {}, metadata: {}, created_at: ISO, updated_at: ISO }
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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('ChatClient.sendTo', () => {
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

  it('creates a fresh thread, adds identity, joins', async () => {
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
    const thread = await client.sendTo({ identity: ALICE })

    expect(thread.id).toBe('th_new')
    expect(order).toEqual(['createThread', 'addMember', 'joinThread'])
  })

  it('reuses existing thread when threadId is provided', async () => {
    const order: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'GET' && url.endsWith('/chat/threads/th_existing')) {
        order.push('getThread')
        return jsonResponse(threadResponse('th_existing'))
      }
      if (method === 'POST' && url.endsWith('/chat/threads/th_existing/members')) {
        order.push('addMember')
        return jsonResponse(memberResponse('th_existing', 'u_alice'), 201)
      }
      if (method === 'POST' && url.endsWith('/chat/threads')) {
        order.push('createThread!UNEXPECTED')
        return jsonResponse(threadResponse('th_should_not_create'), 201)
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    })
    emitWithAck.mockImplementation(async (event: string) => {
      if (event === 'thread:join') {
        order.push('joinThread')
        return { thread_id: 'th_existing', replayed: [], replay_truncated: false }
      }
      throw new Error(`unexpected emit: ${event}`)
    })

    const client = new ChatClient({
      url: 'http://chat.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
    await client.connect()
    const thread = await client.sendTo({ identity: ALICE, threadId: 'th_existing' })

    expect(thread.id).toBe('th_existing')
    expect(order).toEqual(['getThread', 'addMember', 'joinThread'])
  })

  it('forwards clientId for thread idempotency', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'POST' && url.endsWith('/chat/threads')) {
        const body = JSON.parse(init?.body as string) as Record<string, unknown>
        expect(body.client_id).toBe('op_alpha')
        return jsonResponse(threadResponse('th_new'), 201)
      }
      if (method === 'POST' && url.endsWith('/chat/threads/th_new/members')) {
        return jsonResponse(memberResponse('th_new', 'u_alice'), 201)
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    })
    emitWithAck.mockResolvedValue({ thread_id: 'th_new', replayed: [], replay_truncated: false })

    const client = new ChatClient({
      url: 'http://chat.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
    await client.connect()
    await client.sendTo({ identity: ALICE, clientId: 'op_alpha' })
  })

  it('forwards tenant + metadata to createThread', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'POST' && url.endsWith('/chat/threads')) {
        const body = JSON.parse(init?.body as string) as Record<string, unknown>
        expect(body.tenant).toEqual({ org: 'X' })
        expect(body.metadata).toEqual({ kind: 'dm' })
        return jsonResponse(threadResponse('th_new'), 201)
      }
      if (method === 'POST' && url.endsWith('/chat/threads/th_new/members')) {
        return jsonResponse(memberResponse('th_new', 'u_alice'), 201)
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    })
    emitWithAck.mockResolvedValue({ thread_id: 'th_new', replayed: [], replay_truncated: false })

    const client = new ChatClient({
      url: 'http://chat.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
    await client.connect()
    await client.sendTo({ identity: ALICE, tenant: { org: 'X' }, metadata: { kind: 'dm' } })
  })

  it('joins the thread room via socket', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'POST' && url.endsWith('/chat/threads')) {
        return jsonResponse(threadResponse('th_new'), 201)
      }
      if (method === 'POST' && url.endsWith('/chat/threads/th_new/members')) {
        return jsonResponse(memberResponse('th_new', 'u_alice'), 201)
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    })
    emitWithAck.mockResolvedValue({ thread_id: 'th_new', replayed: [], replay_truncated: false })

    const client = new ChatClient({
      url: 'http://chat.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
    await client.connect()
    await client.sendTo({ identity: ALICE })

    expect(emitWithAck).toHaveBeenCalledWith('thread:join', { thread_id: 'th_new' })
  })

  it('does not send any message — only setup (caller emits via useThreadActions)', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = (init?.method ?? 'GET').toUpperCase()
      if (method === 'POST' && url.endsWith('/chat/threads')) {
        return jsonResponse(threadResponse('th_new'), 201)
      }
      if (method === 'POST' && url.endsWith('/chat/threads/th_new/members')) {
        return jsonResponse(memberResponse('th_new', 'u_alice'), 201)
      }
      if (method === 'POST' && url.endsWith('/chat/threads/th_new/messages')) {
        throw new Error('sendMessage should NOT be called by sendTo')
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    })
    emitWithAck.mockResolvedValue({ thread_id: 'th_new', replayed: [], replay_truncated: false })

    const client = new ChatClient({
      url: 'http://chat.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
    await client.connect()
    const thread = await client.sendTo({ identity: ALICE })
    expect(thread.id).toBe('th_new')
  })
})
