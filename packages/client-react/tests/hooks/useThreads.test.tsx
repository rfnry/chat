import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client/ChatClient'
import { useThreads } from '../../src/hooks/useThreads'
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

function Probe({ onResult }: { onResult: (r: { data?: unknown; isLoading: boolean }) => void }) {
  const result = useThreads({ limit: 10 })
  onResult({ data: result.data, isLoading: result.isLoading })
  return null
}

describe('useThreads', () => {
  it('calls client.listThreads and surfaces the page', async () => {
    const client = {
      listThreads: vi.fn().mockResolvedValue({
        items: [
          { id: 'th_1', tenant: {}, metadata: {}, createdAt: '', updatedAt: '' },
          { id: 'th_2', tenant: {}, metadata: {}, createdAt: '', updatedAt: '' },
        ],
        nextCursor: null,
      }),
    } as unknown as ChatClient
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const Wrapper = wrapper(client, qc)
    const seen: Array<{ data?: unknown; isLoading: boolean }> = []

    render(
      <Wrapper>
        <Probe onResult={(r) => seen.push(r)} />
      </Wrapper>
    )

    await waitFor(() => {
      const last = seen[seen.length - 1]
      expect(last?.isLoading).toBe(false)
      expect((last?.data as { items: unknown[] }).items).toHaveLength(2)
    })
    expect(client.listThreads).toHaveBeenCalledWith({ limit: 10 })
  })
})
