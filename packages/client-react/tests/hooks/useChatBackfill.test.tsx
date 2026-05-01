import type { Event } from '@rfnry/chat-protocol'
import { act, render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { type ChatBackfill, useChatBackfill } from '../../src/hooks/useChatBackfill'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'
import { createPresenceSlice } from '../../src/store/presence'

const noopEvents = { subscribe: () => () => {} }

function harness(client: Partial<ChatClient>, store: ReturnType<typeof createChatStore>) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider
      value={{
        client: client as ChatClient,
        store,
        events: noopEvents,
        presence: createPresenceSlice(),
      }}
    >
      {children}
    </ChatContext.Provider>
  )
}

function makeEvent(id: string, createdAt: string): Event {
  return {
    type: 'message',
    id,
    threadId: 'th_1',
    runId: undefined,
    author: { role: 'user', id: 'u_1', name: 'U', metadata: {} },
    createdAt,
    metadata: {},
    recipients: null,
    content: [{ type: 'text', text: id }],
  } as Event
}

describe('useChatBackfill', () => {
  it('does nothing when there are no local events to anchor', async () => {
    const store = createChatStore()
    const backfillMock = vi.fn(async () => ({ events: [], hasMore: false }))
    const Wrapper = harness({ backfill: backfillMock as unknown as ChatClient['backfill'] }, store)
    const captured: ChatBackfill[] = []
    function Probe() {
      const bf = useChatBackfill('th_1')
      captured.push(bf)
      return null
    }
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    await act(async () => {
      await captured.at(-1)?.loadOlder(50)
    })
    expect(backfillMock).not.toHaveBeenCalled()
    expect(captured.at(-1)?.hasMore).toBe(false)
  })

  it('uses the oldest local event as the anchor and merges results', async () => {
    const store = createChatStore()
    store.getState().actions.addEvent(makeEvent('evt_anchor', '2026-04-21T00:00:00Z'))
    const older = makeEvent('evt_old', '2026-04-20T00:00:00Z')
    const backfillMock = vi.fn(async () => ({ events: [older], hasMore: false }))
    const Wrapper = harness({ backfill: backfillMock as unknown as ChatClient['backfill'] }, store)
    const captured: ChatBackfill[] = []
    function Probe() {
      const bf = useChatBackfill('th_1')
      captured.push(bf)
      return null
    }
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    await act(async () => {
      await captured.at(-1)?.loadOlder(50)
    })
    expect(backfillMock).toHaveBeenCalledWith('th_1', {
      before: { createdAt: '2026-04-21T00:00:00Z', id: 'evt_anchor' },
      limit: 50,
    })
    expect(store.getState().events.th_1).toHaveLength(2)
    expect(store.getState().events.th_1?.[0]?.id).toBe('evt_old')
    expect(captured.at(-1)?.hasMore).toBe(false)
  })

  it('hasMore stays true when result fills the requested limit', async () => {
    const store = createChatStore()
    store.getState().actions.addEvent(makeEvent('evt_anchor', '2026-04-21T00:00:00Z'))
    const filled = Array.from({ length: 50 }, (_, i) =>
      makeEvent(`evt_${i}`, `2026-04-20T00:00:0${i % 10}Z`)
    )
    const backfillMock = vi.fn(async () => ({ events: filled, hasMore: true }))
    const Wrapper = harness({ backfill: backfillMock as unknown as ChatClient['backfill'] }, store)
    const captured: ChatBackfill[] = []
    function Probe() {
      const bf = useChatBackfill('th_1')
      captured.push(bf)
      return null
    }
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    await act(async () => {
      await captured.at(-1)?.loadOlder(50)
    })
    await waitFor(() => expect(captured.at(-1)?.hasMore).toBe(true))
  })

  it('captures errors without throwing to the consumer', async () => {
    const store = createChatStore()
    store.getState().actions.addEvent(makeEvent('evt_anchor', '2026-04-21T00:00:00Z'))
    const backfillMock = vi.fn(async () => {
      throw new Error('boom')
    })
    const Wrapper = harness({ backfill: backfillMock as unknown as ChatClient['backfill'] }, store)
    const captured: ChatBackfill[] = []
    function Probe() {
      const bf = useChatBackfill('th_1')
      captured.push(bf)
      return null
    }
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    await act(async () => {
      await captured.at(-1)?.loadOlder(50)
    })
    expect(captured.at(-1)?.error).toBeInstanceOf(Error)
    expect(captured.at(-1)?.error?.message).toBe('boom')
  })
})
