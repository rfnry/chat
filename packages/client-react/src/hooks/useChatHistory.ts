import type { Event } from '@rfnry/chat-protocol'
import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

const EMPTY: Event[] = []

/**
 * Returns the persisted, server-confirmed event log for `threadId` in
 * chronological order. Mirrors Python's `client.get_events` semantics —
 * the canonical record, immutable past, no in-flight partials.
 *
 * For the rendering primitive that interleaves history with live streaming
 * partials, use {@link useChatTranscript} instead.
 */
export function useChatHistory(threadId: string | null): Event[] {
  const store = useChatStore()
  return useStore(store, (state) => (threadId ? (state.events[threadId] ?? EMPTY) : EMPTY))
}
