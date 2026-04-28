import type {
  ContentPart,
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
  ToolCallEvent,
  ToolResultEvent,
} from '@rfnry/chat-protocol'
import { useCallback, useMemo, useTransition } from 'react'
import type { Stream } from '../stream'
import { useChatClient } from './useChatClient'

export type WithRunSend = {
  threadId: string
  runId: string | null
  message: (
    content: ContentPart[],
    opts?: { recipients?: string[]; metadata?: Record<string, unknown> }
  ) => Promise<MessageEvent>
  reasoning: (
    text: string,
    opts?: { recipients?: string[]; metadata?: Record<string, unknown> }
  ) => Promise<ReasoningEvent>
  toolCall: (
    name: string,
    args: unknown,
    opts?: { id?: string; recipients?: string[]; metadata?: Record<string, unknown> }
  ) => Promise<ToolCallEvent>
  toolResult: (
    toolId: string,
    result?: unknown,
    opts?: {
      error?: { code: string; message: string }
      recipients?: string[]
      metadata?: Record<string, unknown>
    }
  ) => Promise<ToolResultEvent>
  emit: <E extends Event>(event: E) => Promise<E>
  streamMessage: (opts?: {
    author?: Identity
    metadata?: Record<string, unknown>
    onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
  }) => Stream
  streamReasoning: (opts?: {
    author?: Identity
    metadata?: Record<string, unknown>
    onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
  }) => Stream
}

export type WithRunOptions = {
  triggeredBy?: Event | Identity
  triggeredByEventId?: string
  idempotencyKey?: string
  lazy?: boolean
}

export type UseThreadActions = {
  isPending: boolean
  send: (draft: EventDraft) => Promise<Event>
  emit: (event: Record<string, unknown> & { type: string }) => Promise<Event>
  beginRun: (opts?: {
    triggeredBy?: Event | Identity
    triggeredByEventId?: string
    idempotencyKey?: string
  }) => Promise<Run>
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
  withRun: <T>(callback: (send: WithRunSend) => Promise<T>, opts?: WithRunOptions) => Promise<T>
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

  // Callbacks are stable across isPending toggles. Components that memo
  // on individual action references (e.g. useEffect(..., [actions.send]))
  // don't re-fire when transitions tick the pending state.
  const callbacks = useMemo(
    () => ({
      send: (draft: EventDraft) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.sendMessage(threadId, draft))
      },
      emit: (event: Record<string, unknown> & { type: string }) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.emitEvent({ ...event, threadId }))
      },
      beginRun: (
        opts: {
          triggeredBy?: Event | Identity
          triggeredByEventId?: string
          idempotencyKey?: string
        } = {}
      ) => {
        if (!threadId) throw new Error('threadId is required')
        return withTransition(() => client.beginRun(threadId, opts))
      },
      endRun: (runId: string, opts: { error?: RunError } = {}) =>
        withTransition(() => client.endRun(runId, opts)),
      cancelRun: (runId: string) => withTransition(() => client.cancelRun(runId)),
      streamMessage: ({
        runId,
        author,
        metadata,
        onFinalEvent,
      }: {
        runId: string
        author: Identity
        metadata?: Record<string, unknown>
        onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
      }) => {
        if (!threadId) throw new Error('threadId is required')
        return client.streamMessage({ threadId, runId, author, metadata, onFinalEvent })
      },
      streamReasoning: ({
        runId,
        author,
        metadata,
        onFinalEvent,
      }: {
        runId: string
        author: Identity
        metadata?: Record<string, unknown>
        onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void
      }) => {
        if (!threadId) throw new Error('threadId is required')
        return client.streamReasoning({ threadId, runId, author, metadata, onFinalEvent })
      },
      addMember: (identity: Identity, role: string = 'member') => {
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
      withRun: async <T>(
        callback: (send: WithRunSend) => Promise<T>,
        opts: WithRunOptions = {}
      ): Promise<T> => {
        if (!threadId) throw new Error('threadId is required')
        const author = client.identity
        if (!author) throw new Error('withRun requires an authenticated identity')

        let runId: string | null = null
        const startRun = async (): Promise<string> => {
          if (runId) return runId
          const run = await client.beginRun(threadId, {
            triggeredBy: opts.triggeredBy,
            triggeredByEventId: opts.triggeredByEventId,
            idempotencyKey: opts.idempotencyKey,
          })
          runId = run.id
          return runId
        }

        if (!opts.lazy) await startRun()

        const buildBase = async () => {
          const rid = await startRun()
          return {
            id: `evt_${crypto.randomUUID().replace(/-/g, '').slice(0, 16)}`,
            thread_id: threadId,
            run_id: rid,
            author,
            created_at: new Date().toISOString(),
            metadata: {} as Record<string, unknown>,
          }
        }

        const send: WithRunSend = {
          threadId,
          get runId() {
            return runId
          },
          message: async (content, msgOpts = {}) => {
            const base = await buildBase()
            const event = {
              ...base,
              type: 'message' as const,
              content,
              metadata: msgOpts.metadata ?? {},
              recipients: msgOpts.recipients ?? null,
            }
            return (await client.emitEvent(
              event as unknown as Record<string, unknown> & { threadId: string }
            )) as MessageEvent
          },
          reasoning: async (text, msgOpts = {}) => {
            const base = await buildBase()
            const event = {
              ...base,
              type: 'reasoning' as const,
              content: text,
              metadata: msgOpts.metadata ?? {},
              recipients: msgOpts.recipients ?? null,
            }
            return (await client.emitEvent(
              event as unknown as Record<string, unknown> & { threadId: string }
            )) as ReasoningEvent
          },
          toolCall: async (name, args, toolOpts = {}) => {
            const base = await buildBase()
            const event = {
              ...base,
              type: 'tool.call' as const,
              tool: {
                id: toolOpts.id ?? `call_${crypto.randomUUID().replace(/-/g, '').slice(0, 16)}`,
                name,
                arguments: args,
              },
              metadata: toolOpts.metadata ?? {},
              recipients: toolOpts.recipients ?? null,
            }
            return (await client.emitEvent(
              event as unknown as Record<string, unknown> & { threadId: string }
            )) as ToolCallEvent
          },
          toolResult: async (toolId, result, toolOpts = {}) => {
            const base = await buildBase()
            const event = {
              ...base,
              type: 'tool.result' as const,
              tool: { id: toolId, result, error: toolOpts.error ?? null },
              metadata: toolOpts.metadata ?? {},
              recipients: toolOpts.recipients ?? null,
            }
            return (await client.emitEvent(
              event as unknown as Record<string, unknown> & { threadId: string }
            )) as ToolResultEvent
          },
          emit: async (event) => {
            const rid = await startRun()
            const stamped = {
              ...(event as unknown as Record<string, unknown>),
              run_id: (event as unknown as { run_id?: unknown }).run_id ?? rid,
              created_at: new Date().toISOString(),
              threadId,
            }
            return (await client.emitEvent(
              stamped as unknown as Record<string, unknown> & { threadId: string }
            )) as typeof event
          },
          streamMessage: (streamOpts = {}) => {
            if (!runId)
              throw new Error(
                'streamMessage requires the run to be open; remove lazy or emit first'
              )
            return client.streamMessage({
              threadId,
              runId,
              author: streamOpts.author ?? author,
              metadata: streamOpts.metadata,
              onFinalEvent: streamOpts.onFinalEvent,
            })
          },
          streamReasoning: (streamOpts = {}) => {
            if (!runId)
              throw new Error(
                'streamReasoning requires the run to be open; remove lazy or emit first'
              )
            return client.streamReasoning({
              threadId,
              runId,
              author: streamOpts.author ?? author,
              metadata: streamOpts.metadata,
              onFinalEvent: streamOpts.onFinalEvent,
            })
          },
        }

        try {
          const result = await callback(send)
          if (runId) await client.endRun(runId)
          return result
        } catch (err) {
          if (runId) {
            await client.endRun(runId, {
              error: {
                code: 'send_error',
                message: err instanceof Error ? err.message : String(err),
              },
            })
          }
          throw err
        }
      },
    }),
    [client, threadId, withTransition] // NOTE: no isPending here
  )

  return { ...callbacks, isPending }
}
