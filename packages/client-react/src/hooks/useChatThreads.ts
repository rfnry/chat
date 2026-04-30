import type { Thread } from '@rfnry/chat-protocol'
import { type UseQueryResult, useQuery } from '@tanstack/react-query'
import type { Page } from '../client'
import { useChatClient } from './useChatClient'

export type UseChatThreadsOptions = {
  limit?: number
}

export function useChatThreads(
  options: UseChatThreadsOptions = {}
): UseQueryResult<Page<Thread>, Error> {
  const client = useChatClient()
  const limit = options.limit ?? 50
  return useQuery({
    queryKey: ['chat', 'threads', limit],
    queryFn: () => client.listThreads({ limit }),
  })
}
