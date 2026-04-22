import type { Event } from '@rfnry/chat-protocol'
import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

const EMPTY: Event[] = []

export function useThreadEvents(threadId: string | null): Event[] {
  const store = useChatStore()
  // Subscribe to a stable slice — only re-render when this thread's event
  // array reference changes. Other threads' addEvent calls no longer wake
  // this hook.
  return useStore(store, (state) => (threadId ? (state.events[threadId] ?? EMPTY) : EMPTY))
}
