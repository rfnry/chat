import type { Identity } from '@rfnry/chat-protocol'
import { useSyncExternalStore } from 'react'
import { useChatStore } from './useChatClient'

const EMPTY: Identity[] = []

export function useThreadMembers(threadId: string | null): Identity[] {
  const store = useChatStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => (threadId ? (store.getState().members[threadId] ?? EMPTY) : EMPTY),
    () => (threadId ? (store.getState().members[threadId] ?? EMPTY) : EMPTY)
  )
}
