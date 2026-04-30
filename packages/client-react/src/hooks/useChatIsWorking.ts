import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

/**
 * Returns `true` if any run for `threadId` is `pending` or `running`.
 * Cheap subscription — only flips when the boolean state changes (~2x per
 * assistant turn). Use this for spinners and "thinking..." gates.
 *
 * For the latest interesting event in an active run, see
 * {@link useChatWorkingDetail}.
 */
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
