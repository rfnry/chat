import type { Event } from '@rfnry/chat-protocol'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatClient } from '../../src/client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const messageWire = {
  id: 'evt_msg_1',
  thread_id: 'th_1',
  type: 'message',
  author: { role: 'user', id: 'u_me', name: 'Me', metadata: {} },
  created_at: '2026-04-21T00:00:00Z',
  metadata: {},
  recipients: null,
  content: [{ type: 'text', text: 'hi' }],
}

describe('ChatClient optimistic insert (Case 5)', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let client: ChatClient

  beforeEach(() => {
    fetchMock = vi.fn()
    client = new ChatClient({
      url: 'http://test',
      identity: { role: 'user', id: 'u_me', name: 'Me', metadata: {} },
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
  })

  it('sendMessage dispatches the canonical event to onDomainEvent listeners', async () => {
    fetchMock.mockResolvedValue(jsonResponse(messageWire))
    const received: Event[] = []
    client.onDomainEvent((e) => received.push(e))

    const event = await client.sendMessage('th_1', {
      clientId: 'c_1',
      content: [{ type: 'text', text: 'hi' }],
    })

    expect(event.id).toBe('evt_msg_1')
    expect(received).toHaveLength(1)
    expect(received[0]?.id).toBe('evt_msg_1')
  })

  it('a throwing listener does not break the send chain', async () => {
    fetchMock.mockResolvedValue(jsonResponse(messageWire))
    const calls: string[] = []
    client.onDomainEvent(() => {
      throw new Error('handler boom')
    })
    client.onDomainEvent((e) => {
      calls.push(e.id)
    })

    const event = await client.sendMessage('th_1', {
      clientId: 'c_1',
      content: [{ type: 'text', text: 'hi' }],
    })

    expect(event.id).toBe('evt_msg_1')
    expect(calls).toEqual(['evt_msg_1'])

    fetchMock.mockResolvedValue(jsonResponse({ ...messageWire, id: 'evt_msg_2' }))
    const next = await client.sendMessage('th_1', {
      clientId: 'c_2',
      content: [{ type: 'text', text: 'again' }],
    })
    expect(next.id).toBe('evt_msg_2')
  })

  it('unsubscribe stops further onDomainEvent calls', async () => {
    fetchMock.mockResolvedValue(jsonResponse(messageWire))
    const received: Event[] = []
    const off = client.onDomainEvent((e) => received.push(e))
    off()
    await client.sendMessage('th_1', {
      clientId: 'c_1',
      content: [{ type: 'text', text: 'hi' }],
    })
    expect(received).toHaveLength(0)
  })
})
