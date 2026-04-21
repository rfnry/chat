import type { Event } from '@rfnry/chat-protocol'
import { useSyncExternalStore } from 'react'
import { useChatStore } from './useChatClient'

const EMPTY: Event[] = []

export function useThreadEvents(threadId: string | null): Event[] {
  const store = useChatStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => (threadId ? (store.getState().events[threadId] ?? EMPTY) : EMPTY),
    () => (threadId ? (store.getState().events[threadId] ?? EMPTY) : EMPTY)
  )
}
