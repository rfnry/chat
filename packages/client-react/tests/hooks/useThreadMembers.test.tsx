import { act, render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useThreadMembers } from '../../src/hooks/useThreadMembers'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function Probe() {
  const members = useThreadMembers('th_1')
  return <div data-testid="count">{members.length}</div>
}

describe('useThreadMembers', () => {
  it('returns empty array when no members loaded', () => {
    const store = createChatStore()
    const { getByTestId } = render(
      <ChatContext.Provider
        value={{ client: {} as ChatClient, store, events: { subscribe: () => () => {} } }}
      >
        <Probe />
      </ChatContext.Provider>
    )
    expect(getByTestId('count').textContent).toBe('0')
  })

  it('reflects setMembers updates', () => {
    const store = createChatStore()
    const { getByTestId } = render(
      <ChatContext.Provider
        value={{ client: {} as ChatClient, store, events: { subscribe: () => () => {} } }}
      >
        <Probe />
      </ChatContext.Provider>
    )

    act(() => {
      store.getState().actions.setMembers('th_1', [
        { role: 'user', id: 'u1', name: 'Alice', metadata: {} },
        { role: 'assistant', id: 'a1', name: 'Helper', metadata: {} },
      ])
    })
    expect(getByTestId('count').textContent).toBe('2')

    act(() => {
      store
        .getState()
        .actions.setMembers('th_1', [{ role: 'user', id: 'u1', name: 'Alice', metadata: {} }])
    })
    expect(getByTestId('count').textContent).toBe('1')
  })

  it('returns the same reference for unchanged state (reference stability)', () => {
    const store = createChatStore()
    const seen: Array<readonly unknown[]> = []
    function Probe2() {
      const members = useThreadMembers('th_1')
      seen.push(members)
      return null
    }
    const { rerender } = render(
      <ChatContext.Provider
        value={{ client: {} as ChatClient, store, events: { subscribe: () => () => {} } }}
      >
        <Probe2 />
      </ChatContext.Provider>
    )
    rerender(
      <ChatContext.Provider
        value={{ client: {} as ChatClient, store, events: { subscribe: () => () => {} } }}
      >
        <Probe2 />
      </ChatContext.Provider>
    )
    // Identical empty-array reference across renders (prevents
    // `useSyncExternalStore` infinite-loop detection).
    expect(seen[0]).toBe(seen[1])
  })
})
