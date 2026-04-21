import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useCreateThread } from '../../src/hooks/useCreateThread'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function wrapper(client: ChatClient, qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ChatContext.Provider value={{ client, store: createChatStore() }}>
        {children}
      </ChatContext.Provider>
    </QueryClientProvider>
  )
}

function Probe({
  onMutate,
}: {
  onMutate: (fn: (input: { tenant?: Record<string, string> }) => Promise<unknown>) => void
}) {
  const m = useCreateThread()
  onMutate(m.mutateAsync)
  return null
}

describe('useCreateThread', () => {
  it('creates a thread and invalidates the threads query', async () => {
    const client = {
      createThread: vi.fn().mockResolvedValue({
        id: 'th_new',
        tenant: { org: 'A' },
        metadata: {},
        createdAt: '2026-04-10T00:00:00Z',
        updatedAt: '2026-04-10T00:00:00Z',
      }),
    } as unknown as ChatClient
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const Wrapper = wrapper(client, qc)

    let mutateAsync: ((i: { tenant?: Record<string, string> }) => Promise<unknown>) | null = null
    render(
      <Wrapper>
        <Probe
          onMutate={(fn) => {
            mutateAsync = fn
          }}
        />
      </Wrapper>
    )

    await waitFor(() => expect(mutateAsync).not.toBeNull())
    const result = (await mutateAsync!({ tenant: { org: 'A' } })) as { id: string }
    expect(result.id).toBe('th_new')
    expect(client.createThread).toHaveBeenCalledWith({ tenant: { org: 'A' } })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['chat', 'threads'] })
  })
})
