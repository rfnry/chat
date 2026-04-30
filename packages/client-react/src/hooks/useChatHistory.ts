import type { Event } from '@rfnry/chat-protocol'
import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

const EMPTY: Event[] = []

export function useChatHistory(threadId: string | null): Event[] {
  const store = useChatStore()
  return useStore(store, (state) => (threadId ? (state.events[threadId] ?? EMPTY) : EMPTY))
}
