import type { Event, Identity, Run } from '@rfnry/chat-protocol'
import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useChatWorkingDetail } from '../../src/hooks/useChatWorkingDetail'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'
import { createPresenceSlice } from '../../src/store/presence'

const noopEvents = { subscribe: () => () => {} }
const ASSISTANT: Identity = { role: 'assistant', id: 'bot', name: 'Bot', metadata: {} }

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

function makeRun(id: string, threadId: string, status: Run['status'] = 'running'): Run {
  return {
    id,
    threadId,
    actor: ASSISTANT,
    triggeredBy: ASSISTANT,
    status,
    startedAt: '2026-04-21T00:00:00Z',
    metadata: {},
  } as Run
}

function makeEvent(id: string, threadId: string, runId: string, type: Event['type']): Event {
  const base = {
    id,
    threadId,
    runId,
    author: ASSISTANT,
    createdAt: '2026-04-21T00:00:00Z',
    metadata: {},
    recipients: null,
  }
  if (type === 'reasoning') return { ...base, type: 'reasoning', content: 'thinking' } as Event
  if (type === 'tool.call')
    return {
      ...base,
      type: 'tool.call',
      tool: { id: 'c1', name: 'do', arguments: {} },
    } as Event
  if (type === 'tool.result')
    return {
      ...base,
      type: 'tool.result',
      tool: { id: 'c1', result: 'ok' },
    } as Event
  return { ...base, type: 'message', content: [{ type: 'text', text: 'm' }] } as Event
}

describe('useChatWorkingDetail', () => {
  it('returns null when no run is active', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const detail = useChatWorkingDetail('th_1')
      return <span data-testid="d">{detail ? detail.id : 'null'}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('d').textContent).toBe('null')
  })

  it('returns the latest reasoning/tool.call/tool.result tied to an active run', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const detail = useChatWorkingDetail('th_1')
      return <span data-testid="d">{detail ? detail.id : 'null'}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    act(() => {
      store.getState().actions.upsertRun(makeRun('r1', 'th_1'))
      store.getState().actions.addEvent(makeEvent('e1', 'th_1', 'r1', 'reasoning'))
      store.getState().actions.addEvent(makeEvent('e2', 'th_1', 'r1', 'tool.call'))
    })
    expect(getByTestId('d').textContent).toBe('e2')
  })

  it('ignores message events (only interesting types count)', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const detail = useChatWorkingDetail('th_1')
      return <span data-testid="d">{detail ? detail.id : 'null'}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    act(() => {
      store.getState().actions.upsertRun(makeRun('r1', 'th_1'))
      store.getState().actions.addEvent(makeEvent('e1', 'th_1', 'r1', 'reasoning'))
      store.getState().actions.addEvent(makeEvent('e2', 'th_1', 'r1', 'message'))
    })
    expect(getByTestId('d').textContent).toBe('e1')
  })

  it('returns null when the run has completed (not in active set)', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const detail = useChatWorkingDetail('th_1')
      return <span data-testid="d">{detail ? detail.id : 'null'}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    act(() => {
      store.getState().actions.upsertRun(makeRun('r1', 'th_1'))
      store.getState().actions.addEvent(makeEvent('e1', 'th_1', 'r1', 'reasoning'))
      store.getState().actions.upsertRun(makeRun('r1', 'th_1', 'completed'))
    })
    expect(getByTestId('d').textContent).toBe('null')
  })

  it('returns null for null threadId', () => {
    const store = createChatStore()
    const Wrapper = harness(store)
    function Probe() {
      const detail = useChatWorkingDetail(null)
      return <span data-testid="d">{detail ? detail.id : 'null'}</span>
    }
    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('d').textContent).toBe('null')
  })
})
