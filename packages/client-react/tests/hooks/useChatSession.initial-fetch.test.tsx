import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useChatSession } from '../../src/hooks/useChatSession'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

import { createPresenceSlice } from '../../src/store/presence'

const noopEvents = { subscribe: () => () => {} }

function harness(client: ChatClient, store: ReturnType<typeof createChatStore>) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider
      value={{ client, store, events: noopEvents, presence: createPresenceSlice() }}
    >
      {children}
    </ChatContext.Provider>
  )
}

function Probe({ threadId }: { threadId: string }) {
  const session = useChatSession(threadId)
  return <div data-testid="status">{session.status}</div>
}

describe('useChatSession initial fetch', () => {
  it('populates thread metadata and members after a successful join', async () => {
    const client = {
      joinThread: vi.fn().mockResolvedValue({
        threadId: 'th_1',
        replayTruncated: false,
        replayed: [],
      }),
      leaveThread: vi.fn().mockResolvedValue(undefined),
      getThread: vi.fn().mockResolvedValue({
        id: 'th_1',
        tenant: { org: 'A' },
        metadata: { title: 'x' },
        createdAt: '2026-04-10T00:00:00Z',
        updatedAt: '2026-04-10T00:00:00Z',
      }),
      listMembers: vi.fn().mockResolvedValue([
        {
          threadId: 'th_1',
          identityId: 'u1',
          identity: { role: 'user', id: 'u1', name: 'A', metadata: {} },
          role: 'member',
          addedAt: '2026-04-10T00:00:00Z',
          addedBy: { role: 'user', id: 'u1', name: 'A', metadata: {} },
        },
      ]),
    } as unknown as ChatClient

    const store = createChatStore()
    const Wrapper = harness(client, store)

    const { getByTestId } = render(
      <Wrapper>
        <Probe threadId="th_1" />
      </Wrapper>
    )

    await waitFor(() => expect(getByTestId('status').textContent).toBe('joined'))
    await waitFor(() => {
      expect(store.getState().threadMeta.th_1?.id).toBe('th_1')
      expect(store.getState().members.th_1).toHaveLength(1)
      expect(store.getState().members.th_1?.[0]?.id).toBe('u1')
    })
    expect(client.getThread).toHaveBeenCalledWith('th_1')
    expect(client.listMembers).toHaveBeenCalledWith('th_1')
  })

  it('stays in joined status even if the initial fetches fail', async () => {
    const client = {
      joinThread: vi.fn().mockResolvedValue({
        threadId: 'th_1',
        replayTruncated: false,
        replayed: [],
      }),
      leaveThread: vi.fn().mockResolvedValue(undefined),
      getThread: vi.fn().mockRejectedValue(new Error('boom')),
      listMembers: vi.fn().mockRejectedValue(new Error('boom')),
    } as unknown as ChatClient

    const store = createChatStore()
    const Wrapper = harness(client, store)
    const { getByTestId } = render(
      <Wrapper>
        <Probe threadId="th_1" />
      </Wrapper>
    )

    await waitFor(() => expect(getByTestId('status').textContent).toBe('joined'))
    // Flush any pending rejections
    await new Promise((r) => setTimeout(r, 0))
    expect(getByTestId('status').textContent).toBe('joined')
    expect(store.getState().threadMeta.th_1).toBeUndefined()
  })
})
