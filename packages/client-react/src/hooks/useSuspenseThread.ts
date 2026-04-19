import { useSuspenseQuery } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import type { Thread } from '../protocol/thread'
import { useChatClient, useChatStore } from './useChatClient'

/**
 * Suspense-compatible thread snapshot.
 *
 * Uses TanStack Query's `useSuspenseQuery` to fetch the thread via REST and
 * throws a promise to the nearest `<Suspense>` boundary until the fetch
 * resolves. On resolution, the thread is also written into the Zustand store
 * via `setThreadMeta`, so subsequent live `thread:updated` socket events
 * flow through and this hook re-renders with the latest state.
 *
 * Pair with `<Suspense fallback={...}>`:
 *
 * ```tsx
 * <Suspense fallback={<Loading />}>
 *   <ThreadHeader threadId="th_1" />
 * </Suspense>
 *
 * function ThreadHeader({ threadId }: { threadId: string }) {
 *   const thread = useSuspenseThread(threadId)
 *   return <h1>{String(thread.metadata.title ?? thread.id)}</h1>
 * }
 * ```
 *
 * Use {@link useThreadMetadata} instead if you need a `Thread | null` selector
 * without Suspense (e.g., when `threadId` can be `null`).
 */
export function useSuspenseThread(threadId: string): Thread {
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

  const live = useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => store.getState().threadMeta[threadId],
    () => store.getState().threadMeta[threadId]
  )

  return live ?? initial
}
