import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useChatThreads } from '../../src/hooks/useChatThreads'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

import { createPresenceSlice } from '../../src/store/presence'

const noopEvents = { subscribe: () => () => {} }

function wrapper(client: ChatClient, qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ChatContext.Provider
        value={{
          client,
          store: createChatStore(),
          events: noopEvents,
          presence: createPresenceSlice(),
        }}
      >
        {children}
      </ChatContext.Provider>
    </QueryClientProvider>
  )
}

function Probe({ onResult }: { onResult: (r: { data?: unknown; isLoading: boolean }) => void }) {
  const result = useChatThreads({ limit: 10 })
  onResult({ data: result.data, isLoading: result.isLoading })
  return null
}

describe('useChatThreads', () => {
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
