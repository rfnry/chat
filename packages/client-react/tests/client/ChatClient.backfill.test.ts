import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatClient } from '../../src/client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const eventWire = (id: string, createdAt: string) => ({
  id,
  thread_id: 'th_1',
  type: 'message',
  author: { role: 'user', id: 'u_1', name: 'U', metadata: {} },
  created_at: createdAt,
  metadata: {},
  recipients: null,
  content: [{ type: 'text', text: id }],
})

describe('ChatClient.backfill', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let client: ChatClient

  beforeEach(() => {
    fetchMock = vi.fn()
    client = new ChatClient({
      url: 'http://test',
      identity: { role: 'user', id: 'u_1', name: 'U', metadata: {} },
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
  })

  it('passes before_created_at + before_id query params', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        items: [eventWire('evt_old', '2026-04-20T00:00:00Z')],
        next_cursor: null,
      })
    )

    await client.backfill('th_1', {
      before: { createdAt: '2026-04-21T00:00:00Z', id: 'evt_anchor' },
      limit: 50,
    })

    const url = fetchMock.mock.calls[0]?.[0] as string
    expect(url).toContain('before_created_at=')
    expect(url).toContain('before_id=evt_anchor')
    expect(url).toContain('limit=50')
  })

  it('returns events + hasMore=true when result fills the limit', async () => {
    const items = Array.from({ length: 50 }, (_, i) =>
      eventWire(`evt_${i}`, '2026-04-20T00:00:00Z')
    )
    fetchMock.mockResolvedValue(jsonResponse({ items, next_cursor: null }))

    const result = await client.backfill('th_1', {
      before: { createdAt: '2026-04-21T00:00:00Z', id: 'evt_anchor' },
      limit: 50,
    })

    expect(result.events).toHaveLength(50)
    expect(result.hasMore).toBe(true)
  })

  it('returns hasMore=false when result is shorter than the limit', async () => {
    const items = [eventWire('evt_old', '2026-04-20T00:00:00Z')]
    fetchMock.mockResolvedValue(jsonResponse({ items, next_cursor: null }))

    const result = await client.backfill('th_1', {
      before: { createdAt: '2026-04-21T00:00:00Z', id: 'evt_anchor' },
      limit: 100,
    })

    expect(result.events).toHaveLength(1)
    expect(result.hasMore).toBe(false)
  })
})
