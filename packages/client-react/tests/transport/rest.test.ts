import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RestTransport } from '../../src/transport/rest'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('RestTransport.listPresence', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let rest: RestTransport

  beforeEach(() => {
    fetchMock = vi.fn()
    rest = new RestTransport({
      baseUrl: 'http://localhost:8000',
      fetchImpl: fetchMock as unknown as typeof fetch,
      authenticate: async () => ({ authorization: 'Bearer xyz' }),
    })
  })

  it('GETs /chat/presence and parses the snapshot', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        members: [
          { role: 'user', id: 'u_a', name: 'Alice', metadata: {} },
          { role: 'assistant', id: 'agent-a', name: 'Agent A', metadata: {} },
        ],
      })
    )

    const snapshot = await rest.listPresence()

    expect(snapshot.members).toHaveLength(2)
    expect(snapshot.members[0]).toEqual({
      role: 'user',
      id: 'u_a',
      name: 'Alice',
      metadata: {},
    })
    expect(snapshot.members[1]).toEqual({
      role: 'assistant',
      id: 'agent-a',
      name: 'Agent A',
      metadata: {},
    })

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('http://localhost:8000/chat/presence')
    expect((init as RequestInit).method).toBe('GET')
    const headers = (init as RequestInit).headers as Record<string, string>
    expect(headers.authorization).toBe('Bearer xyz')
  })
})
