import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { type ChatSession, useChatSession } from '../../src/hooks/useChatSession'
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

function makeClient(replayTruncated: boolean): Partial<ChatClient> {
  return {
    joinThread: vi.fn(async () => ({
      threadId: 'th_1',
      replayed: [],
      replayTruncated,
    })),
    leaveThread: vi.fn(async () => undefined),
    getThread: vi.fn(async () => {
      throw new Error('not under test')
    }),
    listMembers: vi.fn(async () => []),
  }
}

describe('useChatSession replayTruncated surfacing (Case 1)', () => {
  it('exposes replayTruncated=true when the server caps the replay window', async () => {
    const captured: ChatSession[] = []
    function Probe() {
      const session = useChatSession('th_1')
      captured.push(session)
      return null
    }
    const Wrapper = harness(makeClient(true))
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    await waitFor(() => expect(captured.at(-1)?.status).toBe('joined'))
    expect(captured.at(-1)?.replayTruncated).toBe(true)
  })

  it('exposes replayTruncated=false when the replay covered the gap', async () => {
    const captured: ChatSession[] = []
    function Probe() {
      const session = useChatSession('th_1')
      captured.push(session)
      return null
    }
    const Wrapper = harness(makeClient(false))
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    await waitFor(() => expect(captured.at(-1)?.status).toBe('joined'))
    expect(captured.at(-1)?.replayTruncated).toBe(false)
  })

  it('replayTruncated is undefined while joining', () => {
    const captured: ChatSession[] = []
    function Probe() {
      const session = useChatSession('th_1')
      captured.push(session)
      return null
    }
    const Wrapper = harness({
      joinThread: vi.fn(
        () =>
          new Promise<{ threadId: string; replayed: never[]; replayTruncated: boolean }>(() => {})
      ),
      leaveThread: vi.fn(async () => undefined),
    })
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    const joining = captured.find((s) => s.status === 'joining')
    expect(joining).toBeDefined()
    expect(joining?.replayTruncated).toBeUndefined()
  })
})
