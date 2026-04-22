import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

export function useThreadIsWorking(threadId: string | null): boolean {
  const store = useChatStore()
  return useStore(store, (state) => {
    if (!threadId) return false
    const runs = state.activeRuns[threadId]
    return runs !== undefined && Object.keys(runs).length > 0
  })
}
