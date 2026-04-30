import { useMemo } from 'react'
import { useStore } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import type { StreamingItem } from '../store/chatStore'
import { useChatStore } from './useChatClient'

const EMPTY: Record<string, StreamingItem> = {}

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
