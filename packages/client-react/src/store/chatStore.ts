import type { Event, Identity, Run, Thread } from '@rfnry/chat-protocol'
import { createStore } from 'zustand/vanilla'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting'

export type ChatStoreState = {
  events: Record<string, Event[]>
  members: Record<string, Identity[]>
  threadMeta: Record<string, Thread>
  activeRuns: Record<string, Record<string, Run>>
  joinedThreads: Set<string>
  connectionStatus: ConnectionStatus
  actions: {
    addEvent(event: Event): void
    setEventsBulk(threadId: string, events: Event[]): void
    clearThreadEvents(threadId: string): void
    setMembers(threadId: string, members: Identity[]): void
    setThreadMeta(thread: Thread): void
    upsertRun(run: Run): void
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

const initialState = (): Omit<ChatStoreState, 'actions'> => ({
  events: {},
  members: {},
  threadMeta: {},
  activeRuns: {},
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
          const next = [...existing, event].sort(compareEvents)
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
          return {
            ...state,
            events: { ...state.events, [event.threadId]: next },
            activeRuns,
          }
        }),
      setEventsBulk: (threadId, events) =>
        set((state) => {
          const map = new Map<string, Event>()
          for (const e of state.events[threadId] ?? []) map.set(e.id, e)
          for (const e of events) map.set(e.id, e)
          const merged = Array.from(map.values()).sort(compareEvents)
          return { ...state, events: { ...state.events, [threadId]: merged } }
        }),
      clearThreadEvents: (threadId) =>
        set((state) => {
          const nextEvents = { ...state.events }
          nextEvents[threadId] = []
          const nextActive = { ...state.activeRuns }
          nextActive[threadId] = {}
          return { ...state, events: nextEvents, activeRuns: nextActive }
        }),
      setMembers: (threadId, members) =>
        set((state) => ({
          ...state,
          members: { ...state.members, [threadId]: members },
        })),
      setThreadMeta: (thread) =>
        set((state) => ({
          ...state,
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
            ...state,
            activeRuns: { ...state.activeRuns, [run.threadId]: threadRuns },
          }
        }),
      addJoinedThread: (threadId) =>
        set((state) => {
          const next = new Set(state.joinedThreads)
          next.add(threadId)
          return { ...state, joinedThreads: next }
        }),
      removeJoinedThread: (threadId) =>
        set((state) => {
          const next = new Set(state.joinedThreads)
          next.delete(threadId)
          return { ...state, joinedThreads: next }
        }),
      setConnectionStatus: (status) => set((state) => ({ ...state, connectionStatus: status })),
      reset: () => set(() => ({ ...initialState() })),
    },
  }))
}

export type ChatStore = ReturnType<typeof createChatStore>
