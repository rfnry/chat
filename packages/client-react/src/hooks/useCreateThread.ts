import type { TenantScope, Thread } from '@rfnry/chat-protocol'
import { type UseMutationResult, useMutation, useQueryClient } from '@tanstack/react-query'
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
