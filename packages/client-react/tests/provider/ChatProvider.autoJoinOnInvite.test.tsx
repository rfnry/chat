import { QueryClient } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { useContext } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Hoisted mock so the provider's `import { io } from 'socket.io-client'` sees our fake.
const { socketOn, socketOnce, socketDisconnect, socketEmitWithAck } = vi.hoisted(() => ({
  socketOn: vi.fn(),
  socketOnce: vi.fn(),
  socketDisconnect: vi.fn(),
  socketEmitWithAck: vi.fn(),
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
    emitWithAck: socketEmitWithAck,
  })),
}))

import type { useChatStore } from '../../src/hooks/useChatClient'
import { ChatContext } from '../../src/provider/ChatContext'
import { ChatProvider } from '../../src/provider/ChatProvider'

function StoreProbe({ onStore }: { onStore: (s: ReturnType<typeof useChatStore>) => void }) {
  const ctx = useContext(ChatContext)
  if (ctx) onStore(ctx.store)
  return null
}

describe('ChatProvider — autoJoinOnInvite={false}', () => {
  beforeEach(() => {
    socketOn.mockClear()
    socketOnce.mockClear()
    socketDisconnect.mockClear()
    socketEmitWithAck.mockClear()
    socketEmitWithAck.mockResolvedValue({
      thread_id: 'th_X',
      replayed: [],
      replay_truncated: false,
    })
  })

  it('still hydrates meta, invalidates queries, and fires onThreadInvited — but does NOT emit thread:join', async () => {
    let captured: ReturnType<typeof useChatStore> | null = null
    const onInvited = vi.fn()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')

    render(
      <ChatProvider
        url="http://x"
        authenticate={async () => ({})}
        queryClient={qc}
        autoJoinOnInvite={false}
        onThreadInvited={onInvited}
      >
        <StoreProbe
          onStore={(s) => {
            captured = s
          }}
        />
      </ChatProvider>
    )

    await waitFor(() => expect(captured).not.toBeNull())

    const call = socketOn.mock.calls.find(([event]) => event === 'thread:invited')
    expect(call).toBeDefined()
    const handler = (call as unknown as [string, (data: unknown) => void])[1]

    handler({
      thread: {
        id: 'th_X',
        tenant: {},
        metadata: { title: 'Proactive ping' },
        created_at: '2026-04-21T00:00:00Z',
        updated_at: '2026-04-21T00:00:00Z',
      },
      added_member: { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} },
      added_by: { role: 'assistant', id: 'a_bot', name: 'Bot', metadata: {} },
    })

    // Meta hydrated, onThreadInvited fired, query invalidated.
    await waitFor(() => {
      const store = captured as unknown as ReturnType<typeof useChatStore>
      expect(store.getState().threadMeta.th_X).toBeDefined()
    })
    await waitFor(() => expect(onInvited).toHaveBeenCalledTimes(1))
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['chat', 'threads'] })

    // Critical: thread:join must NOT have been emitted.
    // Wait a tick for any microtask-scheduled join to flush, then assert.
    await new Promise((r) => setTimeout(r, 10))
    const joinCalls = socketEmitWithAck.mock.calls.filter(([event]) => event === 'thread:join')
    expect(joinCalls).toHaveLength(0)
  })
})
