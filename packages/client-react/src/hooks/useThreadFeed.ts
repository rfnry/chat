import type { Event, Identity } from '@rfnry/chat-protocol'
import { useMemo } from 'react'
import { useStore } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import type { StreamingEntry } from '../store/chatStore'
import { useChatStore } from './useChatClient'

export type FeedItem =
  | { kind: 'event'; event: Event }
  | {
      kind: 'streaming'
      eventId: string
      threadId: string
      runId: string
      author: Identity
      targetType: 'message' | 'reasoning'
      text: string
      createdAt: string
    }

const EMPTY_EVENTS: Event[] = []
const EMPTY_STREAMS: Record<string, StreamingEntry> = {}

export function useThreadFeed(threadId: string | null): FeedItem[] {
  const store = useChatStore()

  // Stable slice: only re-render when this thread's events array reference or
  // the streams record reference changes. Other store updates (members, runs,
  // unrelated threads) do not wake this hook.
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
    const items: FeedItem[] = events.map((event) => ({ kind: 'event' as const, event }))

    for (const eventId in streams) {
      const s = streams[eventId]!
      if (s.threadId !== threadId) continue
      // If the finalized event already arrived (addEvent removes the streaming
      // entry in the same store update), this branch is never reached. The
      // guard here is a belt-and-suspenders check for any transient state
      // where the streaming entry is still present alongside a finalized event.
      if (finalizedIds.has(eventId)) continue
      items.push({
        kind: 'streaming',
        eventId: s.eventId,
        threadId: s.threadId,
        runId: s.runId,
        author: s.author,
        targetType: s.targetType,
        text: s.text,
        createdAt: s.createdAt,
      })
    }

    items.sort((a, b) => {
      const ta = a.kind === 'event' ? a.event.createdAt : a.createdAt
      const tb = b.kind === 'event' ? b.event.createdAt : b.createdAt
      if (ta < tb) return -1
      if (ta > tb) return 1
      return 0
    })

    return items
  }, [threadId, events, streams])
}
