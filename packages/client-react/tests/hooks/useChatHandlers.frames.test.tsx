import type {
  Identity,
  PresenceJoinedFrame,
  PresenceLeftFrame,
  Run,
  Thread,
} from '@rfnry/chat-protocol'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useChatHandlers } from '../../src/hooks/useChatHandlers'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'
import { createPresenceSlice } from '../../src/store/presence'

const noopEvents = { subscribe: () => () => {} }

function harness(client: Partial<ChatClient>) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider
      value={{
        client: client as ChatClient,
        store: createChatStore(),
        events: noopEvents,
        presence: createPresenceSlice(),
      }}
    >
      {children}
    </ChatContext.Provider>
  )
}

type SocketHandler = (data: unknown) => void

function makeMockClient() {
  const handlers = new Map<string, SocketHandler>()
  const off = vi.fn()
  const onSpy = vi.fn((event: string, handler: SocketHandler) => {
    handlers.set(event, handler)
    return off
  })
  return {
    client: { on: onSpy } as unknown as ChatClient,
    fire: (event: string, data: unknown) => handlers.get(event)?.(data),
    onSpy,
    off,
  }
}

const RAW_THREAD = {
  id: 'th_1',
  tenant: {},
  metadata: { title: 'Hello' },
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
}

const RAW_RUN = {
  id: 'run_1',
  thread_id: 'th_1',
  actor: { role: 'assistant', id: 'a_1', name: 'A', metadata: {} },
  triggered_by: { role: 'user', id: 'u_1', name: 'U', metadata: {} },
  status: 'running',
  started_at: '2026-04-21T00:00:00Z',
  metadata: {},
}

const RAW_IDENTITY_USER = { role: 'user', id: 'u_1', name: 'Alice', metadata: {} }

describe('useChatHandlers().on.threadUpdated', () => {
  it('parses the wire payload and delivers Thread', async () => {
    const { client, fire } = makeMockClient()
    const received: Thread[] = []
    function Probe() {
      const { on } = useChatHandlers()
      on.threadUpdated((thread) => {
        received.push(thread)
      })
      return null
    }
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    fire('thread:updated', RAW_THREAD)
    await waitFor(() => expect(received).toHaveLength(1))
    expect(received[0]?.id).toBe('th_1')
    expect(received[0]?.metadata).toMatchObject({ title: 'Hello' })
  })
})

describe('useChatHandlers().on.membersUpdated', () => {
  it('delivers (threadId, Identity[])', async () => {
    const { client, fire } = makeMockClient()
    const calls: { threadId: string; members: Identity[] }[] = []
    function Probe() {
      const { on } = useChatHandlers()
      on.membersUpdated((threadId, members) => {
        calls.push({ threadId, members })
      })
      return null
    }
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    fire('members:updated', { thread_id: 'th_1', members: [RAW_IDENTITY_USER] })
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]?.threadId).toBe('th_1')
    expect(calls[0]?.members[0]?.id).toBe('u_1')
    expect(calls[0]?.members[0]?.name).toBe('Alice')
  })
})

describe('useChatHandlers().on.runUpdated', () => {
  it('parses the wire payload and delivers Run', async () => {
    const { client, fire } = makeMockClient()
    const received: Run[] = []
    function Probe() {
      const { on } = useChatHandlers()
      on.runUpdated((run) => {
        received.push(run)
      })
      return null
    }
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    fire('run:updated', RAW_RUN)
    await waitFor(() => expect(received).toHaveLength(1))
    expect(received[0]?.id).toBe('run_1')
    expect(received[0]?.status).toBe('running')
  })
})

describe('useChatHandlers().on.presenceJoined', () => {
  it('parses the wire payload and delivers PresenceJoinedFrame', async () => {
    const { client, fire } = makeMockClient()
    const received: PresenceJoinedFrame[] = []
    function Probe() {
      const { on } = useChatHandlers()
      on.presenceJoined((frame) => {
        received.push(frame)
      })
      return null
    }
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    fire('presence:joined', { identity: RAW_IDENTITY_USER, at: '2026-04-21T00:00:00Z' })
    await waitFor(() => expect(received).toHaveLength(1))
    expect(received[0]?.identity.id).toBe('u_1')
    expect(received[0]?.at).toBe('2026-04-21T00:00:00Z')
  })
})

describe('useChatHandlers().on.presenceLeft', () => {
  it('parses the wire payload and delivers PresenceLeftFrame', async () => {
    const { client, fire } = makeMockClient()
    const received: PresenceLeftFrame[] = []
    function Probe() {
      const { on } = useChatHandlers()
      on.presenceLeft((frame) => {
        received.push(frame)
      })
      return null
    }
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    fire('presence:left', { identity: RAW_IDENTITY_USER, at: '2026-04-21T00:00:00Z' })
    await waitFor(() => expect(received).toHaveLength(1))
    expect(received[0]?.identity.id).toBe('u_1')
  })
})

describe('frame handlers — handler reference stability', () => {
  it('does not re-subscribe when handler closure changes across renders', async () => {
    const { client, onSpy } = makeMockClient()
    const first = vi.fn()
    const second = vi.fn()

    function Probe({ onFrame }: { onFrame: (t: Thread) => void }) {
      const { on } = useChatHandlers()
      on.threadUpdated(onFrame)
      return null
    }

    const Wrapper = harness(client)
    const { rerender } = render(
      <Wrapper>
        <Probe onFrame={first} />
      </Wrapper>
    )
    await waitFor(() => expect(onSpy).toHaveBeenCalledWith('thread:updated', expect.any(Function)))
    const subsAfterMount = onSpy.mock.calls.length

    rerender(
      <Wrapper>
        <Probe onFrame={second} />
      </Wrapper>
    )
    expect(onSpy.mock.calls.length).toBe(subsAfterMount)
  })
})
