import type { Event, Identity, Run, Thread } from '@rfnry/chat-protocol'
import { createStore } from 'zustand/vanilla'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting'

export type StreamingItem = {
  eventId: string
  threadId: string
  runId: string
  author: Identity
  targetType: 'message' | 'reasoning'
  text: string
  createdAt: string
}

export type ChatStoreState = {
  events: Record<string, Event[]>
  members: Record<string, Identity[]>
  threadMeta: Record<string, Thread>
  activeRuns: Record<string, Record<string, Run>>
  streams: Record<string, StreamingItem>
  joinedThreads: Set<string>
  connectionStatus: ConnectionStatus
  actions: {
    addEvent(event: Event): void
    setEventsBulk(threadId: string, events: Event[]): void
    clearThreadEvents(threadId: string): void
    setMembers(threadId: string, members: Identity[]): void
    setThreadMeta(thread: Thread): void
    upsertRun(run: Run): void
    beginStream(entry: Omit<StreamingItem, 'text' | 'createdAt'>): void
    appendStreamDelta(eventId: string, text: string): void
    endStream(eventId: string): void
    addJoinedThread(threadId: string): void
    removeJoinedThread(threadId: string): void
    setConnectionStatus(status: ConnectionStatus): void
    reset(): void
  }
}

function compareEvents(a: Event, b: Event): number {
  if (a.createdAt < b.createdAt) return -1
  if (a.createdAt > b.createdAt) return 1
  return a.id.localeCompare(b.id)
}

function insertSorted(sorted: Event[], event: Event): Event[] {
  const n = sorted.length
  if (n === 0) return [event]

  if (compareEvents(sorted[n - 1]!, event) <= 0) return [...sorted, event]
  let lo = 0
  let hi = n
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (compareEvents(sorted[mid]!, event) <= 0) lo = mid + 1
    else hi = mid
  }
  return [...sorted.slice(0, lo), event, ...sorted.slice(lo)]
}

const initialState = (): Omit<ChatStoreState, 'actions'> => ({
  events: {},
  members: {},
  threadMeta: {},
  activeRuns: {},
  streams: {},
  joinedThreads: new Set(),
  connectionStatus: 'disconnected',
})

export function createChatStore() {
  return createStore<ChatStoreState>((set) => ({
    ...initialState(),
    actions: {
      addEvent: (event) =>
        set((state) => {
          const existing = state.events[event.threadId] ?? []
          if (existing.some((e) => e.id === event.id)) return state
          const next = insertSorted(existing, event)
          let activeRuns = state.activeRuns
          if (
            (event.type === 'run.completed' ||
              event.type === 'run.failed' ||
              event.type === 'run.cancelled') &&
            event.runId
          ) {
            const threadRuns = { ...(activeRuns[event.threadId] ?? {}) }
            delete threadRuns[event.runId]
            activeRuns = { ...activeRuns, [event.threadId]: threadRuns }
          }

          let streams = state.streams
          if (Object.hasOwn(streams, event.id)) {
            streams = { ...streams }
            delete streams[event.id]
          }
          return {
            events: { ...state.events, [event.threadId]: next },
            activeRuns,
            streams,
          }
        }),
      setEventsBulk: (threadId, events) =>
        set((state) => {
          const map = new Map<string, Event>()
          for (const e of state.events[threadId] ?? []) map.set(e.id, e)
          for (const e of events) map.set(e.id, e)
          const merged = Array.from(map.values()).sort(compareEvents)
          return { events: { ...state.events, [threadId]: merged } }
        }),
      clearThreadEvents: (threadId) =>
        set((state) => {
          const nextEvents = { ...state.events }
          nextEvents[threadId] = []
          const nextActive = { ...state.activeRuns }
          nextActive[threadId] = {}
          return { events: nextEvents, activeRuns: nextActive }
        }),
      setMembers: (threadId, members) =>
        set((state) => ({
          members: { ...state.members, [threadId]: members },
        })),
      setThreadMeta: (thread) =>
        set((state) => ({
          threadMeta: { ...state.threadMeta, [thread.id]: thread },
        })),
      upsertRun: (run) =>
        set((state) => {
          const threadRuns = { ...(state.activeRuns[run.threadId] ?? {}) }
          if (run.status === 'pending' || run.status === 'running') {
            threadRuns[run.id] = run
          } else {
            delete threadRuns[run.id]
          }
          return {
            activeRuns: { ...state.activeRuns, [run.threadId]: threadRuns },
          }
        }),
      beginStream: (entry) =>
        set((state) => ({
          streams: {
            ...state.streams,
            [entry.eventId]: {
              ...entry,
              text: '',
              createdAt: new Date().toISOString(),
            },
          },
        })),
      appendStreamDelta: (eventId, text) =>
        set((state) => {
          const existing = state.streams[eventId]
          if (!existing) return state
          return {
            streams: {
              ...state.streams,
              [eventId]: { ...existing, text: existing.text + text },
            },
          }
        }),
      endStream: (_eventId) => {},
      addJoinedThread: (threadId) =>
        set((state) => {
          const next = new Set(state.joinedThreads)
          next.add(threadId)
          return { joinedThreads: next }
        }),
      removeJoinedThread: (threadId) =>
        set((state) => {
          const next = new Set(state.joinedThreads)
          next.delete(threadId)
          return { joinedThreads: next }
        }),
      setConnectionStatus: (status) => set(() => ({ connectionStatus: status })),
      reset: () => set(() => ({ ...initialState() })),
    },
  }))
}

export type ChatStore = ReturnType<typeof createChatStore>
