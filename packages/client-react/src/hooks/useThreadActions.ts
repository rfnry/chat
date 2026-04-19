import { useCallback, useMemo, useTransition } from 'react'
import type { Event, EventDraft } from '../protocol/event'
import type { Identity } from '../protocol/identity'
import type { Run } from '../protocol/run'
import type { Thread, ThreadMember, ThreadPatch } from '../protocol/thread'
import { useChatClient } from './useChatClient'

export type UseThreadActions = {
  isPending: boolean
  send: (draft: EventDraft) => Promise<Event>
  invoke: (
    assistantIds: string[],
    options?: { idempotencyKey?: string }
  ) => Promise<{ runs: Run[] }>
  ask: (
    assistantIds: string[],
    draft: EventDraft
  ) => Promise<{ message: Event; runs: Run[] | null; error?: Error }>
  cancelRun: (runId: string) => Promise<void>
  addMember: (identity: Identity, role?: string) => Promise<ThreadMember>
  removeMember: (identityId: string) => Promise<void>
  updateThread: (patch: ThreadPatch) => Promise<Thread>
}

export function useThreadActions(threadId: string | null): UseThreadActions {
  const client = useChatClient()
  const [isPending, startTransition] = useTransition()

  // Wrap an async mutation so `isPending` flips true for its duration.
  // We call `startTransition` synchronously inside a Promise constructor so
  // React 19 tracks the async callback's lifetime and flips `isPending` back
  // once the promise settles.
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
      invoke: (assistantIds: string[], options?: { idempotencyKey?: string }) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() =>
          client.invoke(threadId, {
            assistantIds,
            idempotencyKey: options?.idempotencyKey,
          })
        )
      },
      ask: (assistantIds: string[], draft: EventDraft) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(async () => {
          const mergedRecipients = Array.from(
            new Set([...(draft.recipients ?? []), ...assistantIds])
          )
          const message = await client.sendMessage(threadId, {
            ...draft,
            recipients: mergedRecipients,
          })
          return { message, runs: null, error: undefined }
        })
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
