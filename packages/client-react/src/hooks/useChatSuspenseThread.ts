import type { Thread } from '@rfnry/chat-protocol'
import { useSuspenseQuery } from '@tanstack/react-query'
import { useStore } from 'zustand'
import { useChatClient, useChatStore } from './useChatClient'

/**
 * Suspense-compatible thread snapshot.
 *
 * Suspends the nearest `<Suspense>` boundary until the REST fetch resolves;
 * on resolution, writes the thread into the store via `setThreadMeta` so
 * subsequent `thread:updated` socket events flow through and re-render this
 * hook with the latest state.
 *
 * Use {@link useChatThread} for a `Thread | null` selector without Suspense
 * (e.g. when `threadId` may be `null`).
 */
export function useChatSuspenseThread(threadId: string): Thread {
  const client = useChatClient()
  const store = useChatStore()

  const { data: initial } = useSuspenseQuery({
    queryKey: ['chat', 'thread', threadId],
    queryFn: async () => {
      const thread = await client.getThread(threadId)
      store.getState().actions.setThreadMeta(thread)
      return thread
    },
  })

  const live = useStore(store, (state) => state.threadMeta[threadId])

  return live ?? initial
}
