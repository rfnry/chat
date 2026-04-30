import type { Identity } from '@rfnry/chat-protocol'
import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useChatStreams } from '../../src/hooks/useChatStreams'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore, type StreamingItem } from '../../src/store/chatStore'
import { createPresenceSlice } from '../../src/store/presence'

const noopEvents = { subscribe: () => () => {} }
const ASSISTANT: Identity = { role: 'assistant', id: 'bot', name: 'Bot', metadata: {} }

function harness(store: ReturnType<typeof createChatStore>) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider
      value={{
        client: {} as ChatClient,
        store,
        events: noopEvents,
        presence: createPresenceSlice(),
      }}
    >
      {children}
    </ChatContext.Provider>
  )
}

describe('useChatStreams', () => {
  it('returns an empty array when no streams are open', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const items = useChatStreams('th_1')
      return <span data-testid="c">{items.length}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('c').textContent).toBe('0')
  })

  it('returns in-flight partials for the subscribed thread', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    const seen: StreamingItem[][] = []
    function Probe() {
      const items = useChatStreams('th_1')
      seen.push(items)
      return null
    }
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    act(() => {
      store.getState().actions.beginStream({
        eventId: 'ev_a',
        threadId: 'th_1',
        runId: 'r1',
        author: ASSISTANT,
        targetType: 'message',
      })
      store.getState().actions.appendStreamDelta('ev_a', 'hello')
    })
    const last = seen[seen.length - 1]!
    expect(last).toHaveLength(1)
    expect(last[0]?.eventId).toBe('ev_a')
    expect(last[0]?.text).toBe('hello')
  })

  it('excludes partials from other threads', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const items = useChatStreams('th_1')
      return <span data-testid="c">{items.length}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    act(() => {
      store.getState().actions.beginStream({
        eventId: 'ev_other',
        threadId: 'th_2',
        runId: 'r1',
        author: ASSISTANT,
        targetType: 'message',
      })
    })
    expect(getByTestId('c').textContent).toBe('0')
  })

  it('returns empty array for null threadId', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const items = useChatStreams(null)
      return <span data-testid="c">{items.length}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('c').textContent).toBe('0')
  })
})
