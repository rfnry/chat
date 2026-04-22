import type { Event } from '@rfnry/chat-protocol'
import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useThreadEvents } from '../../src/hooks/useThreadEvents'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function makeEvent(id: string, threadId: string, createdAt = '2026-01-01T00:00:00Z'): Event {
  return {
    type: 'message',
    id,
    threadId,
    author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
    createdAt,
    metadata: {},
    recipients: null,
    content: [{ type: 'text', text: id }],
  }
}

const noopEvents = { subscribe: () => () => {} }

function harness(store: ReturnType<typeof createChatStore>) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider value={{ client: {} as ChatClient, store, events: noopEvents }}>
      {children}
    </ChatContext.Provider>
  )
}

describe('useThreadEvents', () => {
  it('returns empty array when no events in store', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    function Probe() {
      const events = useThreadEvents('th_1')
      return <div data-testid="count">{events.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('count').textContent).toBe('0')
  })

  it('reflects addEvent updates for the subscribed thread', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    function Probe() {
      const events = useThreadEvents('th_1')
      return <div data-testid="count">{events.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('count').textContent).toBe('0')

    act(() => {
      store.getState().actions.addEvent(makeEvent('e1', 'th_1'))
    })
    expect(getByTestId('count').textContent).toBe('1')
  })

  it('re-renders when the subscribed thread receives an event', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    let renderCount = 0

    function Probe() {
      renderCount++
      const events = useThreadEvents('t_A')
      return <div data-testid="count">{events.length}</div>
    }

    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    const baseline = renderCount

    act(() => {
      store.getState().actions.addEvent(makeEvent('e1', 't_A'))
    })

    expect(renderCount).toBeGreaterThan(baseline)
  })

  it('returns same EMPTY reference for null threadId (reference stability)', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    const seen: unknown[][] = []

    function Probe() {
      const events = useThreadEvents(null)
      seen.push(events)
      return null
    }

    const { rerender } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    rerender(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    expect(seen[0]).toBe(seen[1])
  })
})
