import { type UseMutationResult, useMutation, useQueryClient } from '@tanstack/react-query'
import type { TenantScope } from '../protocol/tenant'
import type { Thread } from '../protocol/thread'
import { useChatClient } from './useChatClient'

export type CreateThreadInput = {
  tenant?: TenantScope
  metadata?: Record<string, unknown>
}

export function useCreateThread(): UseMutationResult<Thread, Error, CreateThreadInput> {
  const client = useChatClient()
  const qc = useQueryClient()
  return useMutation<Thread, Error, CreateThreadInput>({
    mutationFn: (input) => client.createThread(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chat', 'threads'] })
    },
  })
}
