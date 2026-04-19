import { useSyncExternalStore } from 'react'
import type { Thread } from '../protocol/thread'
import { useChatStore } from './useChatClient'

export function useThreadMetadata(threadId: string | null): Thread | null {
  const store = useChatStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => (threadId ? (store.getState().threadMeta[threadId] ?? null) : null),
    () => (threadId ? (store.getState().threadMeta[threadId] ?? null) : null)
  )
}
