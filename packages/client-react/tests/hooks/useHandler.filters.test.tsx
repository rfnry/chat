import type { Identity, UserIdentity } from '@rfnry/chat-protocol'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useMessageHandler } from '../../src/hooks/useHandler'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function harness(client: Partial<ChatClient> & { identity: Identity | null }) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider value={{ client: client as ChatClient, store: createChatStore() }}>
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

type Raw = ((data: unknown) => void) | null

function makeClient(identity: Identity | null): {
  client: Partial<ChatClient> & { identity: Identity | null }
  getRaw: () => Raw
} {
  let raw: Raw = null
  const client = {
    identity,
    on: vi.fn((_event: string, handler: (data: unknown) => void) => {
      raw = handler
      return () => {}
    }),
  } as Partial<ChatClient> & { identity: Identity | null }
  return { client, getRaw: () => raw }
}

function messageFrom(authorId: string, recipients: string[] | null): Record<string, unknown> {
  return {
    id: `evt_${authorId}`,
    thread_id: 't_1',
    type: 'message',
    author: { role: 'user', id: authorId, name: authorId, metadata: {} },
    created_at: '2026-04-10T00:00:00Z',
    metadata: {},
    recipients,
    content: [{ type: 'text', text: 'hi' }],
  }
}

describe('useHandler default dispatch filters', () => {
  it('skips self-authored events by default', async () => {
    const { client, getRaw } = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await waitFor(() => expect(getRaw()).not.toBeNull())

    getRaw()!(messageFrom('u_me', null))
    await new Promise((r) => setTimeout(r, 10))
    expect(received).toEqual([])
  })

  it('delivers self-authored events when allEvents: true', async () => {
    const { client, getRaw } = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} allEvents />
      </Wrapper>
    )
    await waitFor(() => expect(getRaw()).not.toBeNull())

    getRaw()!(messageFrom('u_me', null))
    await waitFor(() => expect(received.length).toBe(1))
  })

  it('skips events whose recipients list excludes self', async () => {
    const { client, getRaw } = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await waitFor(() => expect(getRaw()).not.toBeNull())

    getRaw()!(messageFrom('u_other', ['u_another_user']))
    await new Promise((r) => setTimeout(r, 10))
    expect(received).toEqual([])
  })

  it('delivers events when recipients is null (broadcast)', async () => {
    const { client, getRaw } = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await waitFor(() => expect(getRaw()).not.toBeNull())

    getRaw()!(messageFrom('u_other', null))
    await waitFor(() => expect(received.length).toBe(1))
  })

  it('delivers events when recipients explicitly includes self', async () => {
    const { client, getRaw } = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await waitFor(() => expect(getRaw()).not.toBeNull())

    getRaw()!(messageFrom('u_other', ['u_me', 'u_third']))
    await waitFor(() => expect(received.length).toBe(1))
  })

  it('filters are inert when client has no identity configured', async () => {
    const { client, getRaw } = makeClient(null)
    const received: unknown[] = []
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await waitFor(() => expect(getRaw()).not.toBeNull())

    // Even a "self-authored" event (same id as the author) gets delivered
    // because there's no self to compare against.
    getRaw()!(messageFrom('u_me', null))
    // And a non-broadcast event with a recipients list goes through too.
    getRaw()!(messageFrom('u_other', ['u_someone']))
    await waitFor(() => expect(received.length).toBe(2))
  })

  it('delivers other-authored broadcast events under default filters (sanity)', async () => {
    const { client, getRaw } = makeClient(me)
    const received: unknown[] = []
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await waitFor(() => expect(getRaw()).not.toBeNull())

    // Other-authored, null recipients → expected to pass through.
    getRaw()!(messageFrom(other.id, null))
    await waitFor(() => expect(received.length).toBe(1))
  })
})
