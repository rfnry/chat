import type { Identity } from '@rfnry/chat-protocol'
import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

const EMPTY: Identity[] = []

export function useThreadMembers(threadId: string | null): Identity[] {
  const store = useChatStore()
  return useStore(store, (state) => (threadId ? (state.members[threadId] ?? EMPTY) : EMPTY))
}
