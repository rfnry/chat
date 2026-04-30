import type {
  AssistantIdentity,
  PresenceJoinedFrame,
  PresenceSnapshot,
  SystemIdentity,
  UserIdentity,
} from '@rfnry/chat-protocol'
import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useChatPresence } from '../../src/hooks/useChatPresence'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'
import { createPresenceSlice, type PresenceSlice } from '../../src/store/presence'

const noopEvents = { subscribe: () => () => {} }

function harness(presence: PresenceSlice) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider
      value={{
        client: {} as ChatClient,
        store: createChatStore(),
        events: noopEvents,
        presence,
      }}
    >
      {children}
    </ChatContext.Provider>
  )
}

const alice: UserIdentity = { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} }
const helper: AssistantIdentity = {
  role: 'assistant',
  id: 'a_helper',
  name: 'Helper',
  metadata: {},
}
const bot: SystemIdentity = { role: 'system', id: 's_bot', name: 'Bot', metadata: {} }

describe('useChatPresence', () => {
  it('exposes members + byRole + isHydrated with initial state', () => {
    const presence = createPresenceSlice()
    let seen: ReturnType<typeof useChatPresence> | undefined
    function Probe() {
      seen = useChatPresence()
      return null
    }
    const Wrapper = harness(presence)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    expect(seen?.members).toEqual([])
    expect(seen?.byRole.user).toEqual([])
    expect(seen?.byRole.assistant).toEqual([])
    expect(seen?.byRole.system).toEqual([])
    expect(seen?.isHydrated).toBe(false)
  })

  it('re-renders when the slice changes', () => {
    const presence = createPresenceSlice()
    let seen: ReturnType<typeof useChatPresence> | undefined
    function Probe() {
      seen = useChatPresence()
      return null
    }
    const Wrapper = harness(presence)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    expect(seen?.members).toHaveLength(0)
    expect(seen?.isHydrated).toBe(false)

    const snapshot: PresenceSnapshot = { members: [alice, helper] }
    act(() => {
      presence.hydrate(snapshot)
    })

    expect(seen?.members).toHaveLength(2)
    expect(seen?.isHydrated).toBe(true)

    const joined: PresenceJoinedFrame = {
      identity: bot,
      at: '2026-04-23T00:00:00.000Z',
    }
    act(() => {
      presence.applyJoined(joined)
    })

    expect(seen?.members).toHaveLength(3)
  })

  it('partitions byRole correctly', () => {
    const presence = createPresenceSlice()
    presence.hydrate({ members: [alice, helper, bot] })

    let seen: ReturnType<typeof useChatPresence> | undefined
    function Probe() {
      seen = useChatPresence()
      return null
    }
    const Wrapper = harness(presence)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    expect(seen?.byRole.user).toEqual([alice])
    expect(seen?.byRole.assistant).toEqual([helper])
    expect(seen?.byRole.system).toEqual([bot])
  })

  it('memoizes byRole across unrelated slice changes', () => {
    const presence = createPresenceSlice()
    presence.hydrate({ members: [alice] })

    const captures: Array<ReturnType<typeof useChatPresence>['byRole']> = []
    function Probe() {
      const { byRole } = useChatPresence()
      captures.push(byRole)
      return null
    }
    const Wrapper = harness(presence)
    const { rerender } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    // Trigger a parent re-render that doesn't change the slice.
    rerender(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    // Applying a duplicate-join is a no-op inside the slice (early return),
    // so no state change happens.
    act(() => {
      presence.applyJoined({
        identity: alice,
        at: '2026-04-23T00:00:00.000Z',
      })
    })

    // At least two captures; all byRole references should be identical.
    expect(captures.length).toBeGreaterThanOrEqual(2)
    const first = captures[0]
    for (const snap of captures) {
      expect(snap).toBe(first)
    }
  })
})
