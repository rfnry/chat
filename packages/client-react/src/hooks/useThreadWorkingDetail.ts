import { useMemo } from 'react'
import type { Event } from '../protocol/event'
import { useThreadActiveRuns } from './useThreadActiveRuns'
import { useThreadEvents } from './useThreadEvents'

const INTERESTING = new Set(['reasoning', 'tool.call', 'tool.result'])

export function useThreadWorkingDetail(threadId: string | null): Event | null {
  const runs = useThreadActiveRuns(threadId)
  const events = useThreadEvents(threadId)
  return useMemo(() => {
    if (runs.length === 0) return null
    const activeRunIds = new Set(runs.map((r) => r.id))
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i]
      if (e?.runId && activeRunIds.has(e.runId) && INTERESTING.has(e.type)) {
        return e
      }
    }
    return null
  }, [runs, events])
}
