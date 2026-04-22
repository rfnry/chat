import { act, render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useThreadEvents } from '../../src/hooks/useThreadEvents'
import { useThreadIsWorking } from '../../src/hooks/useThreadIsWorking'
import { useThreadSession } from '../../src/hooks/useThreadSession'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

const noopEvents = { subscribe: () => () => {} }

function harness(client: ChatClient, store: ReturnType<typeof createChatStore>) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider value={{ client, store, events: noopEvents }}>
      {children}
    </ChatContext.Provider>
  )
}

function Probe({
  threadId,
  onEvents,
  onWorking,
}: {
  threadId: string
  onEvents?: (n: number) => void
  onWorking?: (working: boolean) => void
}) {
  const session = useThreadSession(threadId)
  const events = useThreadEvents(threadId)
  const isWorking = useThreadIsWorking(threadId)
  if (onEvents) onEvents(events.length)
  if (onWorking) onWorking(isWorking)
  return <div data-testid="status">{session.status}</div>
}

describe('hooks integration', () => {
  it('joins thread and surfaces replayed events', async () => {
    const client = {
      joinThread: vi.fn().mockResolvedValue({
        threadId: 'th_1',
        replayTruncated: false,
        replayed: [
          {
            id: 'evt_1',
            threadId: 'th_1',
            type: 'message',
            author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
            createdAt: '2026-04-10T00:00:00Z',
            metadata: {},
            recipients: null,
            content: [{ type: 'text', text: 'hi' }],
          },
        ],
      }),
      leaveThread: vi.fn().mockResolvedValue(undefined),
      getThread: vi.fn().mockResolvedValue({
        id: 'th_1',
        tenant: {},
        metadata: {},
        createdAt: '',
        updatedAt: '',
      }),
      listMembers: vi.fn().mockResolvedValue([]),
    } as unknown as ChatClient

    const store = createChatStore()
    const Wrapper = harness(client, store)
    const seen: number[] = []

    const { getByTestId } = render(
      <Wrapper>
        <Probe threadId="th_1" onEvents={(n) => seen.push(n)} />
      </Wrapper>
    )

    await waitFor(() => {
      expect(getByTestId('status').textContent).toBe('joined')
    })
    expect(store.getState().events.th_1).toHaveLength(1)
    expect(seen[seen.length - 1]).toBe(1)
  })

  it('addEvent (e.g. from socket push) updates subscribers', async () => {
    const client = {
      joinThread: vi.fn().mockResolvedValue({
        threadId: 'th_1',
        replayTruncated: false,
        replayed: [],
      }),
      leaveThread: vi.fn().mockResolvedValue(undefined),
      getThread: vi.fn().mockResolvedValue({
        id: 'th_1',
        tenant: {},
        metadata: {},
        createdAt: '',
        updatedAt: '',
      }),
      listMembers: vi.fn().mockResolvedValue([]),
    } as unknown as ChatClient

    const store = createChatStore()
    const Wrapper = harness(client, store)

    const { getByTestId } = render(
      <Wrapper>
        <Probe threadId="th_1" />
      </Wrapper>
    )

    await waitFor(() => expect(getByTestId('status').textContent).toBe('joined'))

    act(() => {
      store.getState().actions.addEvent({
        id: 'evt_2',
        threadId: 'th_1',
        type: 'message',
        author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
        createdAt: '2026-04-10T00:00:01Z',
        metadata: {},
        recipients: null,
        content: [{ type: 'text', text: 'live' }],
      })
    })

    expect(store.getState().events.th_1).toHaveLength(1)
    expect(store.getState().events.th_1?.[0]?.id).toBe('evt_2')
  })

  it('isWorking flips when active run upserted and clears on completion', async () => {
    const client = {
      joinThread: vi.fn().mockResolvedValue({
        threadId: 'th_1',
        replayTruncated: false,
        replayed: [],
      }),
      leaveThread: vi.fn().mockResolvedValue(undefined),
      getThread: vi.fn().mockResolvedValue({
        id: 'th_1',
        tenant: {},
        metadata: {},
        createdAt: '',
        updatedAt: '',
      }),
      listMembers: vi.fn().mockResolvedValue([]),
    } as unknown as ChatClient

    const store = createChatStore()
    const Wrapper = harness(client, store)
    const states: boolean[] = []

    const { getByTestId } = render(
      <Wrapper>
        <Probe threadId="th_1" onWorking={(w) => states.push(w)} />
      </Wrapper>
    )

    await waitFor(() => expect(getByTestId('status').textContent).toBe('joined'))

    act(() => {
      store.getState().actions.upsertRun({
        id: 'run_1',
        threadId: 'th_1',
        actor: { role: 'assistant', id: 'a1', name: 'H', metadata: {} },
        triggeredBy: { role: 'user', id: 'u1', name: 'A', metadata: {} },
        status: 'running',
        startedAt: '2026-04-10T00:00:00Z',
        metadata: {},
      })
    })
    expect(states[states.length - 1]).toBe(true)

    act(() => {
      store.getState().actions.upsertRun({
        id: 'run_1',
        threadId: 'th_1',
        actor: { role: 'assistant', id: 'a1', name: 'H', metadata: {} },
        triggeredBy: { role: 'user', id: 'u1', name: 'A', metadata: {} },
        status: 'completed',
        startedAt: '2026-04-10T00:00:00Z',
        metadata: {},
      })
    })
    expect(states[states.length - 1]).toBe(false)
  })
})
