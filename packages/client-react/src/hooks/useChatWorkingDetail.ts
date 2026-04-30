import type { Event } from '@rfnry/chat-protocol'
import { useMemo } from 'react'
import { useStore } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import { useChatStore } from './useChatClient'

const INTERESTING = new Set(['reasoning', 'tool.call', 'tool.result'])

export function useChatWorkingDetail(threadId: string | null): Event | null {
  const store = useChatStore()
  const { events, runs } = useStore(
    store,
    useShallow((state) => ({
      events: threadId ? (state.events[threadId] ?? null) : null,
      runs: threadId ? (state.activeRuns[threadId] ?? null) : null,
    }))
  )
  return useMemo(() => {
    if (!events || !runs) return null
    const activeRunIds = new Set(Object.keys(runs))
    if (activeRunIds.size === 0) return null
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i]
      if (e?.runId && activeRunIds.has(e.runId) && INTERESTING.has(e.type)) {
        return e
      }
    }
    return null
  }, [events, runs])
}
