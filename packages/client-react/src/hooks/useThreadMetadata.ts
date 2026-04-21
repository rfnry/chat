import type { Thread } from '@rfnry/chat-protocol'
import { useSyncExternalStore } from 'react'
import { useChatStore } from './useChatClient'

export function useThreadMetadata(threadId: string | null): Thread | null {
  const store = useChatStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => (threadId ? (store.getState().threadMeta[threadId] ?? null) : null),
    () => (threadId ? (store.getState().threadMeta[threadId] ?? null) : null)
  )
}
