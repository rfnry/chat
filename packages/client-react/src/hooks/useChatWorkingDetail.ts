import type { Event } from '@rfnry/chat-protocol'
import { useMemo } from 'react'
import { useStore } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import { useChatStore } from './useChatClient'

const INTERESTING = new Set(['reasoning', 'tool.call', 'tool.result'])

/**
 * Returns the most recent `reasoning | tool.call | tool.result` event whose
 * `runId` is in the active set for `threadId`, or `null` when no run is in
 * flight. Powers "Assistant is calling get_stock(...)" / "Assistant is
 * reasoning..." indicators.
 *
 * Re-renders on every interesting event during an active run (~5-20x per
 * turn). Components that only need a boolean should use
 * {@link useChatIsWorking} instead to avoid unnecessary re-renders.
 */
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
