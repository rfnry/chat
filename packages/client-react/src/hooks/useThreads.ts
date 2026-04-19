import { type UseQueryResult, useQuery } from '@tanstack/react-query'
import type { Page } from '../client/ChatClient'
import type { Thread } from '../protocol/thread'
import { useChatClient } from './useChatClient'

export type UseThreadsOptions = {
  limit?: number
}

export function useThreads(options: UseThreadsOptions = {}): UseQueryResult<Page<Thread>, Error> {
  const client = useChatClient()
  const limit = options.limit ?? 50
  return useQuery({
    queryKey: ['chat', 'threads', limit],
    queryFn: () => client.listThreads({ limit }),
  })
}
