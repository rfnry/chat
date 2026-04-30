import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

export function useChatIsWorking(threadId: string | null): boolean {
  const store = useChatStore()
  return useStore(store, (state) => {
    if (!threadId) return false
    const runs = state.activeRuns[threadId]
    if (runs === undefined) return false
    for (const _k in runs) return true
    return false
  })
}
