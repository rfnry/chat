import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useChatIsWorking } from '../../src/hooks/useChatIsWorking'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

import { createPresenceSlice } from '../../src/store/presence'

function makeRun(id: string, threadId: string) {
  return {
    id,
    threadId,
    status: 'running' as const,
    actor: { role: 'assistant' as const, id: 'a1', name: 'A', metadata: {} },
    triggeredBy: { role: 'user' as const, id: 'u1', name: 'U', metadata: {} },
    startedAt: '2026-01-01T00:00:00Z',
    metadata: {},
  }
}

const noopEvents = { subscribe: () => () => {} }

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

describe('useChatIsWorking', () => {
  it('returns false for empty thread', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const working = useChatIsWorking('t_A')
      return <div data-testid="working">{String(working)}</div>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('working').textContent).toBe('false')
  })

  it('returns true when one run exists', () => {
    const store = createChatStore()
    store.getState().actions.upsertRun(makeRun('r1', 't_A'))
    const Wrapper = harness(store)
    function Probe() {
      const working = useChatIsWorking('t_A')
      return <div data-testid="working">{String(working)}</div>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('working').textContent).toBe('true')
  })

  it('does not re-render when the run set changes but stays non-empty', () => {
    const store = createChatStore()
    store.getState().actions.upsertRun(makeRun('r1', 't_A'))
    const Wrapper = harness(store)
    let renderCount = 0
    function Probe() {
      renderCount++
      const working = useChatIsWorking('t_A')
      return <div>{String(working)}</div>
    }
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    const baseline = renderCount

    act(() => {
      store.getState().actions.upsertRun(makeRun('r2', 't_A'))
    })

    expect(renderCount).toBe(baseline)
  })

  it('returns false for null threadId', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const working = useChatIsWorking(null)
      return <div data-testid="working">{String(working)}</div>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('working').textContent).toBe('false')
  })
})
