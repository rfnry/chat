import type { Event, Identity, UserIdentity } from '@rfnry/chat-protocol'
import { toEvent } from '@rfnry/chat-protocol'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useMessageHandler } from '../../src/hooks/useHandler'
import type { EventListener, EventRegistry } from '../../src/provider/ChatContext'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

import { createPresenceSlice } from '../../src/store/presence'

function makeEventRegistry(): { registry: EventRegistry; dispatch: (event: Event) => void } {
  const listeners = new Set<EventListener>()
  const registry: EventRegistry = {
    subscribe(listener) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
  }
  const dispatch = (event: Event) => {
    for (const l of listeners) l(event)
  }
  return { registry, dispatch }
}

function harness(
  client: Partial<ChatClient> & { identity: Identity | null },
  events: EventRegistry
) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider
      value={{
        client: client as ChatClient,
        store: createChatStore(),
        events,
        presence: createPresenceSlice(),
      }}
    >
      {children}
    </ChatContext.Provider>
  )
}

const me: UserIdentity = { role: 'user', id: 'u_me', name: 'Me', metadata: {} }
const other: UserIdentity = { role: 'user', id: 'u_other', name: 'Other', metadata: {} }

function Probe({ onEvent, allEvents }: { onEvent: (e: unknown) => void; allEvents?: boolean }) {
  useMessageHandler(onEvent, { allEvents })
  return null
}

function makeClient(
  identity: Identity | null
): Partial<ChatClient> & { identity: Identity | null } {
  return { identity } as Partial<ChatClient> & { identity: Identity | null }
}

function messageFrom(authorId: string, recipients: string[] | null): Event {
  return toEvent({
    id: `evt_${authorId}`,
    thread_id: 't_1',
    type: 'message',
    author: { role: 'user', id: authorId, name: authorId, metadata: {} },
    created_at: '2026-04-10T00:00:00Z',
    metadata: {},
    recipients,
    content: [{ type: 'text', text: 'hi' }],
  } as never)
}

describe('useHandler default dispatch filters', () => {
  it('skips self-authored events by default', async () => {
    const { registry, dispatch } = makeEventRegistry()
    const client = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client, registry)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await new Promise((r) => setTimeout(r, 0))

    dispatch(messageFrom('u_me', null))
    await new Promise((r) => setTimeout(r, 10))
    expect(received).toEqual([])
  })

  it('delivers self-authored events when allEvents: true', async () => {
    const { registry, dispatch } = makeEventRegistry()
    const client = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client, registry)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} allEvents />
      </Wrapper>
    )
    await new Promise((r) => setTimeout(r, 0))

    dispatch(messageFrom('u_me', null))
    await waitFor(() => expect(received.length).toBe(1))
  })

  it('skips events whose recipients list excludes self', async () => {
    const { registry, dispatch } = makeEventRegistry()
    const client = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client, registry)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await new Promise((r) => setTimeout(r, 0))

    dispatch(messageFrom('u_other', ['u_another_user']))
    await new Promise((r) => setTimeout(r, 10))
    expect(received).toEqual([])
  })

  it('delivers events when recipients is null (broadcast)', async () => {
    const { registry, dispatch } = makeEventRegistry()
    const client = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client, registry)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await new Promise((r) => setTimeout(r, 0))

    dispatch(messageFrom('u_other', null))
    await waitFor(() => expect(received.length).toBe(1))
  })

  it('delivers events when recipients explicitly includes self', async () => {
    const { registry, dispatch } = makeEventRegistry()
    const client = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client, registry)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await new Promise((r) => setTimeout(r, 0))

    dispatch(messageFrom('u_other', ['u_me', 'u_third']))
    await waitFor(() => expect(received.length).toBe(1))
  })

  it('filters are inert when client has no identity configured', async () => {
    const { registry, dispatch } = makeEventRegistry()
    const client = makeClient(null)
    const received: unknown[] = []
    const Wrapper = harness(client, registry)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await new Promise((r) => setTimeout(r, 0))

    // Even a "self-authored" event (same id as the author) gets delivered
    // because there's no self to compare against.
    dispatch(messageFrom('u_me', null))
    // And a non-broadcast event with a recipients list goes through too.
    dispatch(messageFrom('u_other', ['u_someone']))
    await waitFor(() => expect(received.length).toBe(2))
  })

  it('delivers other-authored broadcast events under default filters (sanity)', async () => {
    const { registry, dispatch } = makeEventRegistry()
    const client = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client, registry)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await new Promise((r) => setTimeout(r, 0))

    // Other-authored, null recipients → expected to pass through.
    dispatch(messageFrom(other.id, null))
    await waitFor(() => expect(received.length).toBe(1))
  })
})
