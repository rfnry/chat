import type {
  Event,
  EventDraft,
  Identity,
  Thread,
  ThreadMember,
  ThreadPatch,
} from '@rfnry/chat-protocol'
import { useCallback, useMemo, useTransition } from 'react'
import { useChatClient } from './useChatClient'

export type UseThreadActions = {
  isPending: boolean
  send: (draft: EventDraft) => Promise<Event>
  cancelRun: (runId: string) => Promise<void>
  addMember: (identity: Identity, role?: string) => Promise<ThreadMember>
  removeMember: (identityId: string) => Promise<void>
  updateThread: (patch: ThreadPatch) => Promise<Thread>
}

export function useThreadActions(threadId: string | null): UseThreadActions {
  const client = useChatClient()
  const [isPending, startTransition] = useTransition()

  const withTransition = useCallback(
    <T>(fn: () => Promise<T>): Promise<T> =>
      new Promise<T>((resolve, reject) => {
        startTransition(async () => {
          try {
            resolve(await fn())
          } catch (err) {
            reject(err as Error)
          }
        })
      }),
    []
  )

  return useMemo(
    () => ({
      isPending,
      send: (draft: EventDraft) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.sendMessage(threadId, draft))
      },
      cancelRun: (runId: string) => withTransition(() => client.cancelRun(runId)),
      addMember: (identity: Identity, role = 'member') => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.addMember(threadId, identity, role))
      },
      removeMember: (identityId: string) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.removeMember(threadId, identityId))
      },
      updateThread: (patch: ThreadPatch) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.updateThread(threadId, patch))
      },
    }),
    [client, threadId, isPending, withTransition]
  )
}
