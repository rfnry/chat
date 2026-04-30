import { useMemo } from 'react'
import { useStore } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import type { StreamingItem } from '../store/chatStore'
import { useChatStore } from './useChatClient'

const EMPTY: Record<string, StreamingItem> = {}

/**
 * Returns the currently in-flight streaming partials for `threadId`.
 *
 * Each item is the live token-accumulation state of an active
 * `streamMessage` or `streamReasoning` call. When a stream completes its
 * partial disappears from this list and a final event lands in
 * {@link useChatHistory}.
 *
 * Plural reflects that multiple streams may be in flight concurrently.
 */
export function useChatStreams(threadId: string | null): StreamingItem[] {
  const store = useChatStore()
  const streams = useStore(
    store,
    useShallow((state) => (threadId ? state.streams : EMPTY))
  )

  return useMemo(() => {
    if (!threadId) return []
    const out: StreamingItem[] = []
    for (const eventId in streams) {
      const s = streams[eventId]!
      if (s.threadId !== threadId) continue
      out.push(s)
    }
    out.sort((a, b) => {
      if (a.createdAt < b.createdAt) return -1
      if (a.createdAt > b.createdAt) return 1
      return 0
    })
    return out
  }, [threadId, streams])
}
