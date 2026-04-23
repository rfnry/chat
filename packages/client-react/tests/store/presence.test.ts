import type { Identity } from '@rfnry/chat-protocol'
import { describe, expect, it } from 'vitest'
import { createPresenceSlice } from '../../src/store/presence'

const alice: Identity = { role: 'user', id: 'u_a', name: 'Alice', metadata: {} }
const bob: Identity = { role: 'user', id: 'u_b', name: 'Bob', metadata: {} }
const agentA: Identity = { role: 'assistant', id: 'agent-a', name: 'Agent A', metadata: {} }

describe('presence slice', () => {
  it('starts unhydrated with empty list', () => {
    const s = createPresenceSlice()
    expect(s.list()).toEqual([])
    expect(s.isHydrated()).toBe(false)
  })

  it('hydrates from snapshot', () => {
    const s = createPresenceSlice()
    s.hydrate({ members: [alice, agentA] })
    expect(
      s
        .list()
        .map((m) => m.id)
        .sort()
    ).toEqual(['agent-a', 'u_a'])
    expect(s.isHydrated()).toBe(true)
  })

  it('applies joined frame', () => {
    const s = createPresenceSlice()
    s.hydrate({ members: [] })
    s.applyJoined({ identity: alice, at: '2026-04-23T12:00:00Z' })
    expect(s.list()).toEqual([alice])
  })

  it('dedupes joined for an already-present identity', () => {
    const s = createPresenceSlice()
    s.hydrate({ members: [alice] })
    s.applyJoined({ identity: alice, at: '2026-04-23T12:00:00Z' })
    expect(s.list()).toEqual([alice])
  })

  it('removes on left', () => {
    const s = createPresenceSlice()
    s.hydrate({ members: [alice, bob] })
    s.applyLeft({ identity: alice, at: '2026-04-23T12:00:00Z' })
    expect(s.list().map((m) => m.id)).toEqual(['u_b'])
  })

  it('ignores left for identity not present', () => {
    const s = createPresenceSlice()
    s.hydrate({ members: [alice] })
    s.applyLeft({ identity: bob, at: '2026-04-23T12:00:00Z' })
    expect(s.list().map((m) => m.id)).toEqual(['u_a'])
  })

  it('re-hydration replaces previous state', () => {
    const s = createPresenceSlice()
    s.hydrate({ members: [alice] })
    s.hydrate({ members: [bob, agentA] })
    expect(
      s
        .list()
        .map((m) => m.id)
        .sort()
    ).toEqual(['agent-a', 'u_b'])
  })
})
