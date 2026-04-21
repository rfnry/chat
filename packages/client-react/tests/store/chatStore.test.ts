import type { Event, Run } from '@rfnry/chat-protocol'
import { describe, expect, it } from 'vitest'
import { createChatStore } from '../../src/store/chatStore'

function makeMessage(id: string, threadId = 'th_1', createdAt = '2026-04-10T00:00:00Z'): Event {
  return {
    type: 'message',
    id,
    threadId,
    author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
    createdAt,
    metadata: {},
    recipients: null,
    content: [{ type: 'text', text: id }],
  }
}

describe('chatStore', () => {
  it('addEvent appends and sorts by createdAt', () => {
    const store = createChatStore()
    store.getState().actions.addEvent(makeMessage('e2', 'th_1', '2026-04-10T00:00:02Z'))
    store.getState().actions.addEvent(makeMessage('e1', 'th_1', '2026-04-10T00:00:01Z'))
    const events = store.getState().events.th_1!
    expect(events.map((e) => e.id)).toEqual(['e1', 'e2'])
  })

  it('addEvent dedupes by id', () => {
    const store = createChatStore()
    store.getState().actions.addEvent(makeMessage('e1'))
    store.getState().actions.addEvent(makeMessage('e1'))
    expect(store.getState().events.th_1).toHaveLength(1)
  })

  it('setEventsBulk merges and dedupes', () => {
    const store = createChatStore()
    store.getState().actions.addEvent(makeMessage('e1', 'th_1', '2026-04-10T00:00:01Z'))
    store
      .getState()
      .actions.setEventsBulk('th_1', [
        makeMessage('e2', 'th_1', '2026-04-10T00:00:02Z'),
        makeMessage('e1', 'th_1', '2026-04-10T00:00:01Z'),
      ])
    expect(store.getState().events.th_1?.map((e) => e.id)).toEqual(['e1', 'e2'])
  })

  it('upsertRun adds active runs and removes terminal ones', () => {
    const store = createChatStore()
    const run: Run = {
      id: 'run_1',
      threadId: 'th_1',
      actor: { role: 'assistant', id: 'a1', name: 'H', metadata: {} },
      triggeredBy: { role: 'user', id: 'u1', name: 'A', metadata: {} },
      status: 'running',
      startedAt: '2026-04-10T00:00:00Z',
      metadata: {},
    }
    store.getState().actions.upsertRun(run)
    expect(store.getState().activeRuns.th_1?.run_1?.status).toBe('running')

    store.getState().actions.upsertRun({ ...run, status: 'completed' })
    expect(store.getState().activeRuns.th_1?.run_1).toBeUndefined()
  })

  it('joinedThreads add/remove', () => {
    const store = createChatStore()
    store.getState().actions.addJoinedThread('th_1')
    expect(store.getState().joinedThreads.has('th_1')).toBe(true)
    store.getState().actions.removeJoinedThread('th_1')
    expect(store.getState().joinedThreads.has('th_1')).toBe(false)
  })

  it('addEvent removes active run on run.completed', () => {
    const store = createChatStore()
    store.getState().actions.upsertRun({
      id: 'run_1',
      threadId: 'th_1',
      actor: { role: 'assistant', id: 'a1', name: 'H', metadata: {} },
      triggeredBy: { role: 'user', id: 'u1', name: 'A', metadata: {} },
      status: 'running',
      startedAt: '2026-04-10T00:00:00Z',
      metadata: {},
    })
    store.getState().actions.addEvent({
      type: 'run.completed',
      id: 'evt_done',
      threadId: 'th_1',
      runId: 'run_1',
      author: { role: 'assistant', id: 'a1', name: 'H', metadata: {} },
      createdAt: '2026-04-10T00:00:01Z',
      metadata: {},
      recipients: null,
    })
    expect(store.getState().activeRuns.th_1?.run_1).toBeUndefined()
  })

  it('setMembers stores per-thread', () => {
    const store = createChatStore()
    store
      .getState()
      .actions.setMembers('th_1', [{ role: 'user', id: 'u1', name: 'A', metadata: {} }])
    expect(store.getState().members.th_1).toHaveLength(1)
  })

  it('setConnectionStatus updates', () => {
    const store = createChatStore()
    store.getState().actions.setConnectionStatus('connected')
    expect(store.getState().connectionStatus).toBe('connected')
  })
})
