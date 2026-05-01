import type { Event, Identity, Run } from '@rfnry/chat-protocol'
import { describe, expect, it } from 'vitest'
import { createChatStore } from '../../src/store/chatStore'

const ASSISTANT: Identity = { role: 'assistant', id: 'bot', name: 'Bot', metadata: {} }
const TS = '2026-04-21T00:00:00Z'

function beginStream(
  store: ReturnType<typeof createChatStore>,
  eventId: string,
  threadId: string,
  runId: string
) {
  store.getState().actions.beginStream({
    eventId,
    threadId,
    runId,
    author: ASSISTANT,
    targetType: 'message',
  })
}

function makeRunEvent(
  threadId: string,
  runId: string,
  type: 'run.completed' | 'run.failed' | 'run.cancelled'
): Event {
  const base = {
    id: `evt_${type}_${runId}`,
    threadId,
    runId,
    author: ASSISTANT,
    createdAt: TS,
    metadata: {},
    recipients: null,
  }
  if (type === 'run.failed') {
    return { ...base, type, error: { code: 'timeout', message: 'reaped' } } as Event
  }
  return { ...base, type } as Event
}

function makeRun(id: string, threadId: string): Run {
  return {
    id,
    threadId,
    actor: ASSISTANT,
    triggeredBy: ASSISTANT,
    status: 'running',
    startedAt: TS,
    metadata: {},
  } as Run
}

describe('chatStore stream lifecycle on terminal run events', () => {
  it('clears the streaming entry when the owning run completes', () => {
    const store = createChatStore()
    store.getState().actions.upsertRun(makeRun('r1', 'th_1'))
    beginStream(store, 'evt_a', 'th_1', 'r1')
    expect(store.getState().streams.evt_a).toBeDefined()

    store.getState().actions.addEvent(makeRunEvent('th_1', 'r1', 'run.completed'))
    expect(store.getState().streams.evt_a).toBeUndefined()
  })

  it('clears the streaming entry when the owning run fails (watchdog reap)', () => {
    const store = createChatStore()
    store.getState().actions.upsertRun(makeRun('r1', 'th_1'))
    beginStream(store, 'evt_a', 'th_1', 'r1')

    store.getState().actions.addEvent(makeRunEvent('th_1', 'r1', 'run.failed'))
    expect(store.getState().streams.evt_a).toBeUndefined()
  })

  it('clears the streaming entry when the owning run is cancelled', () => {
    const store = createChatStore()
    store.getState().actions.upsertRun(makeRun('r1', 'th_1'))
    beginStream(store, 'evt_a', 'th_1', 'r1')

    store.getState().actions.addEvent(makeRunEvent('th_1', 'r1', 'run.cancelled'))
    expect(store.getState().streams.evt_a).toBeUndefined()
  })

  it('only clears streams owned by the terminating run', () => {
    const store = createChatStore()
    store.getState().actions.upsertRun(makeRun('r1', 'th_1'))
    store.getState().actions.upsertRun(makeRun('r2', 'th_1'))
    beginStream(store, 'evt_a', 'th_1', 'r1')
    beginStream(store, 'evt_b', 'th_1', 'r2')

    store.getState().actions.addEvent(makeRunEvent('th_1', 'r1', 'run.failed'))
    expect(store.getState().streams.evt_a).toBeUndefined()
    expect(store.getState().streams.evt_b).toBeDefined()
  })

  it('preserves the existing event-id-based stream cleanup (regression guard)', () => {
    const store = createChatStore()
    beginStream(store, 'evt_x', 'th_1', 'r1')

    const finalEvent: Event = {
      type: 'message',
      id: 'evt_x',
      threadId: 'th_1',
      runId: 'r1',
      author: ASSISTANT,
      createdAt: TS,
      metadata: {},
      recipients: null,
      content: [{ type: 'text', text: 'hello' }],
    } as Event

    store.getState().actions.addEvent(finalEvent)
    expect(store.getState().streams.evt_x).toBeUndefined()
    expect(store.getState().events.th_1).toHaveLength(1)
  })
})
