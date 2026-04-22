import type { Run } from '@rfnry/chat-protocol'
import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useThreadActiveRuns } from '../../src/hooks/useThreadActiveRuns'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function makeRun(id: string, threadId: string, status: Run['status'] = 'running'): Run {
  return {
    id,
    threadId,
    status,
    actor: { role: 'assistant', id: 'a1', name: 'A', metadata: {} },
    triggeredBy: { role: 'user', id: 'u1', name: 'U', metadata: {} },
    startedAt: '2026-01-01T00:00:00Z',
    metadata: {},
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

describe('useThreadActiveRuns', () => {
  it('returns same array reference when an unrelated thread is mutated (useShallow guards re-render)', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    store.getState().actions.upsertRun(makeRun('run_A', 't_A'))

    const seen: Run[][] = []
    function Probe() {
      const runs = useThreadActiveRuns('t_A')
      seen.push(runs)
      return null
    }

    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    const baselineCount = seen.length

    // Mutate a DIFFERENT thread; t_A's runs are unchanged.
    act(() => {
      store.getState().actions.upsertRun(makeRun('run_B', 't_B'))
    })

    // Without useShallow, Object.values(state.activeRuns.t_A) would produce a
    // new array reference and trigger a re-render. With useShallow, contents
    // are unchanged so the hook returns the previous reference and React
    // bails out of re-rendering.
    expect(seen.length).toBe(baselineCount)
  })

  it('re-renders when a run is added to the subscribed thread', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    let renderCount = 0
    function Probe() {
      renderCount++
      const runs = useThreadActiveRuns('t_A')
      return <div data-testid="count">{runs.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    const baseline = renderCount
    expect(getByTestId('count').textContent).toBe('0')

    act(() => {
      store.getState().actions.upsertRun(makeRun('run_1', 't_A'))
    })

    expect(renderCount).toBeGreaterThan(baseline)
    expect(getByTestId('count').textContent).toBe('1')
  })

  it('returns EMPTY for null threadId', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    function Probe() {
      const runs = useThreadActiveRuns(null)
      return <div data-testid="count">{runs.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('count').textContent).toBe('0')
  })
})
