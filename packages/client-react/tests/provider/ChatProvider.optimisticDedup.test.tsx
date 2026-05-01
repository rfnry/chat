import type { Event } from '@rfnry/chat-protocol'
import { render, waitFor } from '@testing-library/react'
import { useContext } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { socketOn, socketOnce, socketDisconnect } = vi.hoisted(() => ({
  socketOn: vi.fn(),
  socketOnce: vi.fn(),
  socketDisconnect: vi.fn(),
}))

vi.mock('socket.io-client', () => ({
  io: vi.fn(() => ({
    on: socketOn,
    off: vi.fn(),
    once: (event: string, cb: (...args: unknown[]) => void) => {
      socketOnce(event, cb)
      if (event === 'connect') queueMicrotask(() => cb())
    },
    disconnect: socketDisconnect,
    emitWithAck: vi.fn(),
  })),
}))

import { ChatContext, type ChatContextValue } from '../../src/provider/ChatContext'
import { ChatProvider } from '../../src/provider/ChatProvider'

function CtxProbe({ onCtx }: { onCtx: (ctx: ChatContextValue) => void }) {
  const ctx = useContext(ChatContext)
  if (ctx) onCtx(ctx)
  return null
}

const messageWire = {
  id: 'evt_dup',
  thread_id: 'th_1',
  type: 'message',
  author: { role: 'user', id: 'u_me', name: 'Me', metadata: {} },
  created_at: '2026-04-21T00:00:00Z',
  metadata: {},
  recipients: null,
  content: [{ type: 'text', text: 'hi' }],
}

describe('ChatProvider optimistic-insert dedup (Case 5)', () => {
  beforeEach(() => {
    socketOn.mockClear()
    socketOnce.mockClear()
    socketDisconnect.mockClear()
  })

  it('listeners fire exactly once when both wire and domain paths deliver the same event id', async () => {
    let captured: ChatContextValue | null = null
    render(
      <ChatProvider
        url="http://x"
        identity={{ role: 'user', id: 'u_me', name: 'Me', metadata: {} }}
        authenticate={async () => ({})}
      >
        <CtxProbe
          onCtx={(c) => {
            captured = c
          }}
        />
      </ChatProvider>
    )
    await waitFor(() => expect(captured).not.toBeNull())
    const ctx = captured as unknown as ChatContextValue

    const received: Event[] = []
    ctx.events.subscribe((e) => received.push(e))

    const wireCall = socketOn.mock.calls.find(([event]) => event === 'event')
    expect(wireCall).toBeDefined()
    const wireHandler = (wireCall as unknown as [string, (data: unknown) => void])[1]

    wireHandler(messageWire)
    ctx.client.onDomainEvent
    // simulate the optimistic-insert path firing for the same event id
    ;(ctx.client as unknown as { _emitDomainEvent: (e: Event) => void })._emitDomainEvent({
      type: 'message',
      id: 'evt_dup',
      threadId: 'th_1',
      runId: null,
      author: { role: 'user', id: 'u_me', name: 'Me', metadata: {} },
      createdAt: '2026-04-21T00:00:00Z',
      metadata: {},
      recipients: null,
      content: [{ type: 'text', text: 'hi' }],
    } as unknown as Event)

    expect(received.filter((e) => e.id === 'evt_dup')).toHaveLength(1)
    expect(ctx.store.getState().events.th_1).toHaveLength(1)
  })
})
