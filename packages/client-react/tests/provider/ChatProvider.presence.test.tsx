import { render, waitFor } from '@testing-library/react'
import { useContext } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { socketOn, socketOff, socketOnce, socketDisconnect, socketEmitWithAck } = vi.hoisted(() => ({
  socketOn: vi.fn(),
  socketOff: vi.fn(),
  socketOnce: vi.fn(),
  socketDisconnect: vi.fn(),
  socketEmitWithAck: vi.fn(),
}))

vi.mock('socket.io-client', () => ({
  io: vi.fn(() => ({
    on: socketOn,
    off: socketOff,
    once: (event: string, cb: (...args: unknown[]) => void) => {
      socketOnce(event, cb)
      if (event === 'connect') queueMicrotask(() => cb())
    },
    disconnect: socketDisconnect,
    emitWithAck: socketEmitWithAck,
  })),
}))

import { ChatContext, type ChatContextValue } from '../../src/provider/ChatContext'
import { ChatProvider } from '../../src/provider/ChatProvider'

function ContextProbe({ onValue }: { onValue: (v: ChatContextValue) => void }) {
  const ctx = useContext(ChatContext)
  if (ctx) onValue(ctx)
  return null
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('ChatProvider presence wiring', () => {
  beforeEach(() => {
    socketOn.mockClear()
    socketOff.mockClear()
    socketOnce.mockClear()
    socketDisconnect.mockClear()
    socketEmitWithAck.mockClear()
  })

  it('hydrates presence from REST and patches via sockets', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        members: [
          { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} },
          { role: 'assistant', id: 'a_bot', name: 'Bot', metadata: {} },
        ],
      })
    )

    let captured: ChatContextValue | null = null
    render(
      <ChatProvider
        url="http://x"
        authenticate={async () => ({})}
        fetchImpl={fetchMock as unknown as typeof fetch}
      >
        <ContextProbe
          onValue={(v) => {
            captured = v
          }}
        />
      </ChatProvider>
    )

    await waitFor(() => expect(captured).not.toBeNull())

    const ctx = captured as unknown as ChatContextValue

    expect(fetchMock).toHaveBeenCalled()
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('http://x/chat/presence')

    await waitFor(() => {
      expect(ctx.presence.isHydrated()).toBe(true)
    })
    const initial = ctx.presence.list()
    expect(initial).toHaveLength(2)
    expect(initial.map((m) => m.id).sort()).toEqual(['a_bot', 'u_alice'])

    const joinedCall = socketOn.mock.calls.find(([event]) => event === 'presence:joined')
    const leftCall = socketOn.mock.calls.find(([event]) => event === 'presence:left')
    expect(joinedCall).toBeDefined()
    expect(leftCall).toBeDefined()
    const onJoined = (joinedCall as unknown as [string, (data: unknown) => void])[1]
    const onLeft = (leftCall as unknown as [string, (data: unknown) => void])[1]

    onJoined({
      identity: { role: 'user', id: 'u_carol', name: 'Carol', metadata: {} },
      at: '2026-04-23T12:00:00Z',
    })
    const afterJoin = ctx.presence.list()
    expect(afterJoin).toHaveLength(3)
    expect(afterJoin.map((m) => m.id)).toContain('u_carol')

    onLeft({
      identity: { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} },
      at: '2026-04-23T12:00:05Z',
    })
    const afterLeft = ctx.presence.list()
    expect(afterLeft).toHaveLength(2)
    expect(afterLeft.map((m) => m.id)).not.toContain('u_alice')
  })

  it('cleans up presence socket listeners on unmount', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ members: [] }))

    let captured: ChatContextValue | null = null
    const { unmount } = render(
      <ChatProvider
        url="http://x"
        authenticate={async () => ({})}
        fetchImpl={fetchMock as unknown as typeof fetch}
      >
        <ContextProbe
          onValue={(v) => {
            captured = v
          }}
        />
      </ChatProvider>
    )

    await waitFor(() => expect(captured).not.toBeNull())

    const joinedCall = socketOn.mock.calls.find(([event]) => event === 'presence:joined')
    const leftCall = socketOn.mock.calls.find(([event]) => event === 'presence:left')
    expect(joinedCall).toBeDefined()
    expect(leftCall).toBeDefined()
    const onJoined = (joinedCall as unknown as [string, (data: unknown) => void])[1]
    const onLeft = (leftCall as unknown as [string, (data: unknown) => void])[1]

    unmount()

    const offCalls = socketOff.mock.calls
    expect(offCalls).toContainEqual(['presence:joined', onJoined])
    expect(offCalls).toContainEqual(['presence:left', onLeft])
  })

  it('does not block the provider when presence REST fails', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const fetchMock = vi.fn().mockResolvedValue(new Response('nope', { status: 500 }))

    let captured: ChatContextValue | null = null
    render(
      <ChatProvider
        url="http://x"
        authenticate={async () => ({})}
        fetchImpl={fetchMock as unknown as typeof fetch}
      >
        <ContextProbe
          onValue={(v) => {
            captured = v
          }}
        />
      </ChatProvider>
    )

    await waitFor(() => expect(captured).not.toBeNull())
    const ctx = captured as unknown as ChatContextValue
    expect(ctx.presence.isHydrated()).toBe(false)
    expect(ctx.presence.list()).toEqual([])
    expect(warnSpy).toHaveBeenCalled()

    warnSpy.mockRestore()
  })
})
