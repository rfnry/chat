import type {
  Event,
  EventDraft,
  Identity,
  MessageEvent,
  ReasoningEvent,
  Run,
  RunError,
  Thread,
  ThreadMember,
  ThreadPatch,
} from '@rfnry/chat-protocol'
import { useCallback, useMemo, useTransition } from 'react'
import type { Stream } from '../stream'
import { useChatClient } from './useChatClient'

export type UseThreadActions = {
  isPending: boolean
  send: (draft: EventDraft) => Promise<Event>
  emit: (event: Record<string, unknown> & { type: string }) => Promise<Event>
  beginRun: (opts?: { triggeredByEventId?: string; idempotencyKey?: string }) => Promise<Run>
  endRun: (runId: string, opts?: { error?: RunError }) => Promise<Run>
  cancelRun: (runId: string) => Promise<void>
  streamMessage: (opts: {
    runId: string
    author: Identity
    metadata?: Record<string, unknown>
    onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
  }) => Stream
  streamReasoning: (opts: {
    runId: string
    author: Identity
    metadata?: Record<string, unknown>
    onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
  }) => Stream
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
      emit: (event) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.emitEvent({ ...event, threadId }))
      },
      beginRun: (opts = {}) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.beginRun(threadId, opts))
      },
      endRun: (runId, opts = {}) => withTransition(() => client.endRun(runId, opts)),
      cancelRun: (runId) => withTransition(() => client.cancelRun(runId)),
      streamMessage: ({ runId, author, metadata, onFinalEvent }) => {
        if (!threadId) throw new Error('threadId is required')
        return client.streamMessage({ threadId, runId, author, metadata, onFinalEvent })
      },
      streamReasoning: ({ runId, author, metadata, onFinalEvent }) => {
        if (!threadId) throw new Error('threadId is required')
        return client.streamReasoning({ threadId, runId, author, metadata, onFinalEvent })
      },
      addMember: (identity, role = 'member') => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.addMember(threadId, identity, role))
      },
      removeMember: (identityId) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.removeMember(threadId, identityId))
      },
      updateThread: (patch) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.updateThread(threadId, patch))
      },
    }),
    [client, threadId, isPending, withTransition]
  )
}
