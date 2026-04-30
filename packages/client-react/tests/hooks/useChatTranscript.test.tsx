import type { Event, Identity } from '@rfnry/chat-protocol'
import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import type { TranscriptItem } from '../../src/hooks/useChatTranscript'
import { useChatTranscript } from '../../src/hooks/useChatTranscript'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'
import { createPresenceSlice } from '../../src/store/presence'

function makeEvent(
  id: string,
  threadId: string,
  createdAt = '2026-01-01T00:00:00Z',
  role: Identity['role'] = 'user'
): Event {
  return {
    type: 'message',
    id,
    threadId,
    author: { role, id: `author-${id}`, name: `Author ${id}`, metadata: {} },
    createdAt,
    metadata: {},
    recipients: null,
    content: [{ type: 'text', text: id }],
  }
}

const ASSISTANT: Identity = { role: 'assistant', id: 'bot-1', name: 'Bot', metadata: {} }

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

describe('useChatTranscript', () => {
  it('returns an empty array when no events or streams exist', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    function Probe() {
      const feed = useChatTranscript('th_1')
      return <div data-testid="count">{feed.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('count').textContent).toBe('0')
  })

  it('returns events ordered chronologically', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    const collected: TranscriptItem[][] = []

    function Probe() {
      const feed = useChatTranscript('th_1')
      collected.push(feed)
      return <div data-testid="count">{feed.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    act(() => {
      store.getState().actions.addEvent(makeEvent('e2', 'th_1', '2026-01-01T00:00:02Z'))
      store.getState().actions.addEvent(makeEvent('e1', 'th_1', '2026-01-01T00:00:01Z'))
      store.getState().actions.addEvent(makeEvent('e3', 'th_1', '2026-01-01T00:00:03Z'))
    })

    expect(getByTestId('count').textContent).toBe('3')
    const last = collected[collected.length - 1]!
    expect(last[0]!.kind).toBe('event')
    expect((last[0] as { kind: 'event'; event: Event }).event.id).toBe('e1')
    expect((last[1] as { kind: 'event'; event: Event }).event.id).toBe('e2')
    expect((last[2] as { kind: 'event'; event: Event }).event.id).toBe('e3')
  })

  it('includes a streaming entry for an open stream', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    const collected: TranscriptItem[][] = []

    function Probe() {
      const feed = useChatTranscript('th_1')
      collected.push(feed)
      return <div data-testid="count">{feed.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    act(() => {
      store.getState().actions.beginStream({
        eventId: 'ev-stream-1',
        threadId: 'th_1',
        runId: 'run-1',
        author: ASSISTANT,
        targetType: 'message',
      })
    })

    expect(getByTestId('count').textContent).toBe('1')
    const last = collected[collected.length - 1]!
    expect(last[0]!.kind).toBe('streaming')
    const item = last[0] as Extract<TranscriptItem, { kind: 'streaming' }>
    expect(item.item.eventId).toBe('ev-stream-1')
    expect(item.item.text).toBe('')

    act(() => {
      store.getState().actions.appendStreamDelta('ev-stream-1', 'Hello ')
      store.getState().actions.appendStreamDelta('ev-stream-1', 'world')
    })

    const afterDeltas = collected[collected.length - 1]!
    const streaming = afterDeltas[0] as Extract<TranscriptItem, { kind: 'streaming' }>
    expect(streaming.item.text).toBe('Hello world')
  })

  it('replaces a streaming entry with the finalized event when it arrives', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    const collected: TranscriptItem[][] = []

    function Probe() {
      const feed = useChatTranscript('th_1')
      collected.push(feed)
      return <div data-testid="count">{feed.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    act(() => {
      store.getState().actions.beginStream({
        eventId: 'ev-fin-1',
        threadId: 'th_1',
        runId: 'run-1',
        author: ASSISTANT,
        targetType: 'message',
      })
      store.getState().actions.appendStreamDelta('ev-fin-1', 'partial text')
    })

    expect(getByTestId('count').textContent).toBe('1')
    expect(collected[collected.length - 1]![0]!.kind).toBe('streaming')

    act(() => {
      store.getState().actions.addEvent(makeEvent('ev-fin-1', 'th_1', '2026-01-01T00:00:01Z'))
    })

    expect(getByTestId('count').textContent).toBe('1')
    const last = collected[collected.length - 1]!
    expect(last[0]!.kind).toBe('event')
    expect((last[0] as { kind: 'event'; event: Event }).event.id).toBe('ev-fin-1')
  })

  it('retains streaming entry after stream:end if finalized event has not arrived yet', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    const collected: TranscriptItem[][] = []

    function Probe() {
      const feed = useChatTranscript('th_1')
      collected.push(feed)
      return <div data-testid="count">{feed.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    act(() => {
      store.getState().actions.beginStream({
        eventId: 'ev-race-1',
        threadId: 'th_1',
        runId: 'run-1',
        author: ASSISTANT,
        targetType: 'message',
      })
      store.getState().actions.appendStreamDelta('ev-race-1', 'some text')
    })

    expect(getByTestId('count').textContent).toBe('1')

    act(() => {
      store.getState().actions.endStream('ev-race-1')
    })

    expect(getByTestId('count').textContent).toBe('1')
    expect(collected[collected.length - 1]![0]!.kind).toBe('streaming')

    act(() => {
      store.getState().actions.addEvent(makeEvent('ev-race-1', 'th_1', '2026-01-01T00:00:01Z'))
    })

    expect(getByTestId('count').textContent).toBe('1')
    expect(collected[collected.length - 1]![0]!.kind).toBe('event')
  })

  it('sorts streaming entries and finalized events together by createdAt', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    const collected: TranscriptItem[][] = []

    function Probe() {
      const feed = useChatTranscript('th_1')
      collected.push(feed)
      return <div data-testid="count">{feed.length}</div>
    }

    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    act(() => {
      store.getState().actions.addEvent(makeEvent('e-finalized', 'th_1', '2026-01-01T00:00:02Z'))
    })

    act(() => {
      store.getState().actions.beginStream({
        eventId: 'ev-stream-later',
        threadId: 'th_1',
        runId: 'run-2',
        author: ASSISTANT,
        targetType: 'reasoning',
      })
    })

    const last = collected[collected.length - 1]!
    expect(last.length).toBe(2)

    expect(last[0]!.kind).toBe('event')
    expect(last[1]!.kind).toBe('streaming')
  })

  it('does not include streaming entries for other threads', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    const collected: TranscriptItem[][] = []

    function Probe() {
      const feed = useChatTranscript('th_1')
      collected.push(feed)
      return <div data-testid="count">{feed.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    act(() => {
      store.getState().actions.beginStream({
        eventId: 'ev-other',
        threadId: 'th_2',
        runId: 'run-1',
        author: ASSISTANT,
        targetType: 'message',
      })
    })

    expect(getByTestId('count').textContent).toBe('0')
  })

  it('returns empty array for null threadId', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    function Probe() {
      const feed = useChatTranscript(null)
      return <div data-testid="count">{feed.length}</div>
    }

    const { getByTestId } = render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(getByTestId('count').textContent).toBe('0')
  })

  it('does not re-render for unrelated thread mutations', () => {
    const store = createChatStore()
    const Wrapper = harness(store)

    let renderCount = 0

    function Probe() {
      renderCount++
      useChatTranscript('th_A')
      return null
    }

    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )

    const baseline = renderCount

    act(() => {
      store.getState().actions.addEvent(makeEvent('e_unrelated', 'th_B', '2026-01-01T00:00:01Z'))
    })

    expect(renderCount).toBe(baseline)
  })
})
