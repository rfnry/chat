import { useCallback, useState } from 'react'
import { useChatClient, useChatStore } from './useChatClient'

export type ChatBackfill = {
  loadOlder: (limit?: number) => Promise<void>
  hasMore: boolean
  isLoading: boolean
  error?: Error
}

export function useChatBackfill(threadId: string | null): ChatBackfill {
  const client = useChatClient()
  const store = useChatStore()
  const [hasMore, setHasMore] = useState<boolean>(true)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [error, setError] = useState<Error | undefined>(undefined)

  const loadOlder = useCallback(
    async (limit: number = 100) => {
      if (!threadId) return
      if (isLoading) return
      const events = store.getState().events[threadId] ?? []
      const oldest = events[0]
      if (!oldest) {
        setHasMore(false)
        return
      }
      setIsLoading(true)
      setError(undefined)
      try {
        const result = await client.backfill(threadId, {
          before: { createdAt: oldest.createdAt, id: oldest.id },
          limit,
        })
        if (result.events.length > 0) {
          store.getState().actions.setEventsBulk(threadId, result.events)
        }
        setHasMore(result.hasMore)
      } catch (err) {
        setError(err as Error)
      } finally {
        setIsLoading(false)
      }
    },
    [client, store, threadId, isLoading]
  )

  return { loadOlder, hasMore, isLoading, error }
}
