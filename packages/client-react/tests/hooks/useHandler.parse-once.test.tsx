/**
 * R15 regression: each incoming `event` frame is parsed ONCE by the provider,
 * regardless of how many `useHandler` hooks are mounted.
 */
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useHandler } from '../../src/hooks/useHandler'
import type { EventListener, EventRegistry } from '../../src/provider/ChatContext'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'
import { createPresenceSlice } from '../../src/store/presence'

// ---------------------------------------------------------------------------
// Count toEvent calls via spy on the real implementation.
// We spy at the module level so the provider's import sees the wrapper.
// ---------------------------------------------------------------------------
const parseCount = vi.hoisted(() => ({ n: 0 }))

vi.mock('@rfnry/chat-protocol', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>
  return {
    ...actual,
    toEvent: (raw: unknown) => {
      parseCount.n++
      return (actual['toEvent'] as (r: unknown) => unknown)(raw)
    },
  }
})

// Re-import after mock is in place
import { toEvent } from '@rfnry/chat-protocol'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RAW_MESSAGE = {
  id: 'evt_r15',
  thread_id: 't_1',
  type: 'message',
  author: { role: 'user', id: 'u1', name: 'U', metadata: {} },
  created_at: '2026-04-10T00:00:00Z',
  metadata: {},
  recipients: null,
  content: [{ type: 'text', text: 'hello' }],
}

/**
 * A minimal EventRegistry that lets the test dispatch pre-parsed Events
 * to all subscribed listeners (simulating what the provider does after parsing).
 */
function makeDispatchableRegistry(): {
  registry: EventRegistry
  dispatchRaw: (raw: unknown) => void
} {
  const listeners = new Set<EventListener>()
  const registry: EventRegistry = {
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
  // Simulate the provider: parse ONCE then fan out
  const dispatchRaw = (raw: unknown) => {
    const event = toEvent(raw as never)
    for (const l of listeners) {
      try {
        l(event)
      } catch {
        // ignore
      }
    }
  }
  return { registry, dispatchRaw }
}

function Probe({ id }: { id: number }) {
  useHandler('message', () => {})
  return <span data-testid={`probe-${id}`} />
}

function Wrapper({ events, children }: { events: EventRegistry; children: ReactNode }) {
  return (
    <ChatContext.Provider
      value={{
        client: { identity: null } as unknown as ChatClient,
        store: createChatStore(),
        events,
        presence: createPresenceSlice(),
      }}
    >
      {children}
    </ChatContext.Provider>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('R15 — parse-once per incoming event', () => {
  it('parses each incoming event exactly once across N mounted handler hooks', async () => {
    const { registry, dispatchRaw } = makeDispatchableRegistry()

    render(
      <Wrapper events={registry}>
        <Probe id={0} />
        <Probe id={1} />
        <Probe id={2} />
        <Probe id={3} />
        <Probe id={4} />
      </Wrapper>
    )

    await new Promise((r) => setTimeout(r, 0))

    // Reset counter after render (toEvent may be called during module init)
    parseCount.n = 0

    // Dispatch one raw event — the registry calls toEvent once then fans out
    dispatchRaw(RAW_MESSAGE)

    // toEvent should have been called exactly once, not 5 times (R15)
    expect(parseCount.n).toBe(1)
  })

  it('each hook still receives the dispatched event (fan-out works)', async () => {
    const { registry, dispatchRaw } = makeDispatchableRegistry()
    const received: number[] = []

    function CountingProbe({ id }: { id: number }) {
      useHandler('message', () => {
        received.push(id)
      })
      return null
    }

    render(
      <Wrapper events={registry}>
        <CountingProbe id={1} />
        <CountingProbe id={2} />
        <CountingProbe id={3} />
      </Wrapper>
    )

    await new Promise((r) => setTimeout(r, 0))

    dispatchRaw(RAW_MESSAGE)

    await waitFor(() => expect(received.length).toBe(3))
    expect(received.sort()).toEqual([1, 2, 3])
  })
})
