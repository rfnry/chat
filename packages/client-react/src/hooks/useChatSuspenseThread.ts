import type { Thread } from '@rfnry/chat-protocol'
import { useSuspenseQuery } from '@tanstack/react-query'
import { useStore } from 'zustand'
import { useChatClient, useChatStore } from './useChatClient'

export function useChatSuspenseThread(threadId: string): Thread {
  const client = useChatClient()
  const store = useChatStore()

  const { data: initial } = useSuspenseQuery({
    queryKey: ['chat', 'thread', threadId],
    queryFn: async () => {
      const thread = await client.getThread(threadId)
      store.getState().actions.setThreadMeta(thread)
      return thread
    },
  })

  const live = useStore(store, (state) => state.threadMeta[threadId])

  return live ?? initial
}
