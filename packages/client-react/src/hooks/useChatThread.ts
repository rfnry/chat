import type { Thread } from '@rfnry/chat-protocol'
import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

export function useChatThread(threadId: string | null): Thread | null {
  const store = useChatStore()
  return useStore(store, (state) => (threadId ? (state.threadMeta[threadId] ?? null) : null))
}
