import { QueryClient } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { useContext } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { socketOn, socketOnce, socketDisconnect, socketEmitWithAck, socketTimeout } = vi.hoisted(
  () => ({
    socketOn: vi.fn(),
    socketOnce: vi.fn(),
    socketDisconnect: vi.fn(),
    socketEmitWithAck: vi.fn(),
    socketTimeout: vi.fn(),
  })
)

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
    timeout: socketTimeout,
  })),
}))

import type { Identity, Thread } from '@rfnry/chat-protocol'
import type { useChatStore } from '../../src/hooks/useChatClient'
import { ChatContext } from '../../src/provider/ChatContext'
import { ChatProvider } from '../../src/provider/ChatProvider'

function StoreProbe({ onStore }: { onStore: (s: ReturnType<typeof useChatStore>) => void }) {
  const ctx = useContext(ChatContext)
  if (ctx) onStore(ctx.store)
  return null
}

describe('ChatProvider — thread:invited', () => {
  beforeEach(() => {
    socketOn.mockClear()
    socketOnce.mockClear()
    socketDisconnect.mockClear()
    socketEmitWithAck.mockClear()
    socketTimeout.mockClear()

    socketEmitWithAck.mockResolvedValue({
      thread_id: 'th_X',
      replayed: [],
      replay_truncated: false,
    })
    socketTimeout.mockReturnValue({ emitWithAck: socketEmitWithAck })
  })

  it('hydrates thread meta, auto-joins, invalidates threads query, and fires onThreadInvited', async () => {
    let captured: ReturnType<typeof useChatStore> | null = null
    const onInvited = vi.fn<(thread: Thread, addedBy: Identity) => void>()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')

    render(
      <ChatProvider
        url="http://x"
        authenticate={async () => ({})}
        queryClient={qc}
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

    await waitFor(() => {
      const store = captured as unknown as ReturnType<typeof useChatStore>
      const meta = store.getState().threadMeta.th_X
      expect(meta).toBeDefined()
      expect(meta?.id).toBe('th_X')
      expect(meta?.metadata).toMatchObject({ title: 'Proactive ping' })
    })

    await waitFor(() => {
      expect(socketEmitWithAck).toHaveBeenCalledWith('thread:join', { thread_id: 'th_X' })
    })

    await waitFor(() => {
      expect(onInvited).toHaveBeenCalledTimes(1)
    })
    const [thread, addedBy] = onInvited.mock.calls[0] as [Thread, Identity]
    expect(thread.id).toBe('th_X')
    expect(addedBy.id).toBe('a_bot')
    expect(addedBy.role).toBe('assistant')

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['chat', 'threads'] })
  })
})
