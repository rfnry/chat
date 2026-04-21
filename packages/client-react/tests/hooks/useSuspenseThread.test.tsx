import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, waitFor } from '@testing-library/react'
import { type ReactNode, Suspense } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useSuspenseThread } from '../../src/hooks/useSuspenseThread'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

const thread1 = {
  id: 'th_1',
  tenant: { org: 'A' },
  metadata: { title: 'First' },
  createdAt: '2026-04-10T00:00:00Z',
  updatedAt: '2026-04-10T00:00:00Z',
}

function wrapper(client: ChatClient, qc: QueryClient, store = createChatStore()) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ChatContext.Provider value={{ client, store }}>
        <Suspense fallback={<div data-testid="loading">loading</div>}>{children}</Suspense>
      </ChatContext.Provider>
    </QueryClientProvider>
  )
}

function Probe() {
  const thread = useSuspenseThread('th_1')
  return <div data-testid="title">{String(thread.metadata.title ?? '')}</div>
}

describe('useSuspenseThread', () => {
  it('suspends during initial load and resolves with the thread', async () => {
    const client = {
      getThread: vi.fn().mockResolvedValue(thread1),
    } as unknown as ChatClient
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const Wrapper = wrapper(client, qc)

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    // First paint shows the Suspense fallback.
    expect(getByTestId('loading').textContent).toBe('loading')

    await waitFor(() => {
      expect(getByTestId('title').textContent).toBe('First')
    })
    expect(client.getThread).toHaveBeenCalledWith('th_1')
  })

  it('writes the fetched thread into the store so other selectors see it', async () => {
    const client = {
      getThread: vi.fn().mockResolvedValue(thread1),
    } as unknown as ChatClient
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const store = createChatStore()
    const Wrapper = wrapper(client, qc, store)

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    await waitFor(() => {
      expect(getByTestId('title').textContent).toBe('First')
    })
    expect(store.getState().threadMeta.th_1?.metadata.title).toBe('First')
  })

  it('reflects live store updates after the initial Suspense resolves', async () => {
    const client = {
      getThread: vi.fn().mockResolvedValue(thread1),
    } as unknown as ChatClient
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const store = createChatStore()
    const Wrapper = wrapper(client, qc, store)

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    await waitFor(() => {
      expect(getByTestId('title').textContent).toBe('First')
    })

    act(() => {
      store.getState().actions.setThreadMeta({ ...thread1, metadata: { title: 'Renamed' } })
    })
    expect(getByTestId('title').textContent).toBe('Renamed')
  })
})
