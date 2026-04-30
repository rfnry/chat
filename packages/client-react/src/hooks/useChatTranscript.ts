import type { Event } from '@rfnry/chat-protocol'
import { useMemo } from 'react'
import { useStore } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import type { StreamingItem } from '../store/chatStore'
import { useChatStore } from './useChatClient'

export type TranscriptItem =
  | { kind: 'event'; event: Event }
  | { kind: 'streaming'; item: StreamingItem }

const EMPTY_EVENTS: Event[] = []
const EMPTY_STREAMS: Record<string, StreamingItem> = {}

export function useChatTranscript(threadId: string | null): TranscriptItem[] {
  const store = useChatStore()

  const { events, streams } = useStore(
    store,
    useShallow((state) => ({
      events: threadId ? (state.events[threadId] ?? EMPTY_EVENTS) : EMPTY_EVENTS,
      streams: threadId ? state.streams : EMPTY_STREAMS,
    }))
  )

  return useMemo(() => {
    if (!threadId) return []

    const finalizedIds = new Set(events.map((e) => e.id))
    const items: TranscriptItem[] = events.map((event) => ({ kind: 'event' as const, event }))

    for (const eventId in streams) {
      const s = streams[eventId]!
      if (s.threadId !== threadId) continue

      if (finalizedIds.has(eventId)) continue
      items.push({ kind: 'streaming', item: s })
    }

    items.sort((a, b) => {
      const ta = a.kind === 'event' ? a.event.createdAt : a.item.createdAt
      const tb = b.kind === 'event' ? b.event.createdAt : b.item.createdAt
      if (ta < tb) return -1
      if (ta > tb) return 1
      return 0
    })

    return items
  }, [threadId, events, streams])
}
