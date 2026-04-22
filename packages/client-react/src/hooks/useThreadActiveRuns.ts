import type { Run } from '@rfnry/chat-protocol'
import { useStore } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import { useChatStore } from './useChatClient'

const EMPTY: Run[] = []

export function useThreadActiveRuns(threadId: string | null): Run[] {
  const store = useChatStore()
  return useStore(
    store,
    useShallow((state) => {
      if (!threadId) return EMPTY
      const runs = state.activeRuns[threadId]
      return runs ? Object.values(runs) : EMPTY
    })
  )
}
