import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useChatStatus } from '../../src/hooks/useChatStatus'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'
import { createPresenceSlice } from '../../src/store/presence'

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

describe('useChatStatus', () => {
  it('returns the initial disconnected status', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const status = useChatStatus()
      return <span data-testid="s">{status}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('s').textContent).toBe('disconnected')
  })

  it('reflects setConnectionStatus updates', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const status = useChatStatus()
      return <span data-testid="s">{status}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    act(() => {
      store.getState().actions.setConnectionStatus('connecting')
    })
    expect(getByTestId('s').textContent).toBe('connecting')
    act(() => {
      store.getState().actions.setConnectionStatus('connected')
    })
    expect(getByTestId('s').textContent).toBe('connected')
  })

  it('does not re-render when unrelated store slices change', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    let renderCount = 0
    function Probe() {
      renderCount++
      useChatStatus()
      return null
    }
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    const baseline = renderCount
    act(() => {
      store
        .getState()
        .actions.setMembers('th_1', [{ role: 'user', id: 'u1', name: 'U', metadata: {} }])
    })
    expect(renderCount).toBe(baseline)
  })
})
