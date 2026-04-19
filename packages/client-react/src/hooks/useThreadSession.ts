import { useEffect, useState } from 'react'
import { useChatClient, useChatStore } from './useChatClient'

export type SessionStatus = 'idle' | 'joining' | 'joined' | 'error'

export type ThreadSession = {
  status: SessionStatus
  error?: Error
}

export function useThreadSession(threadId: string | null): ThreadSession {
  const client = useChatClient()
  const store = useChatStore()
  const [state, setState] = useState<ThreadSession>({ status: 'idle' })

  useEffect(() => {
    if (!threadId) {
      setState({ status: 'idle' })
      return
    }

    let cancelled = false
    setState({ status: 'joining' })

    const join = async () => {
      try {
        const events = store.getState().events[threadId] ?? []
        const last = events[events.length - 1]
        const since = last ? { createdAt: last.createdAt, id: last.id } : undefined

        const result = await client.joinThread(threadId, since)
        if (cancelled) return

        if (result.replayed.length > 0) {
          store.getState().actions.setEventsBulk(threadId, result.replayed)
        }
        store.getState().actions.addJoinedThread(threadId)
        setState({ status: 'joined' })

        // Initial snapshot — background, non-blocking, swallow errors so a
        // failed getThread doesn't flip the session to 'error'.
        void client.getThread(threadId).then(
          (thread) => {
            if (!cancelled) store.getState().actions.setThreadMeta(thread)
          },
          () => undefined
        )
        void client.listMembers(threadId).then(
          (members) => {
            if (!cancelled) {
              store.getState().actions.setMembers(
                threadId,
                members.map((m) => m.identity)
              )
            }
          },
          () => undefined
        )
      } catch (err) {
        if (cancelled) return
        setState({ status: 'error', error: err as Error })
      }
    }
    void join()

    return () => {
      cancelled = true
      void client.leaveThread(threadId).catch(() => undefined)
      store.getState().actions.removeJoinedThread(threadId)
    }
  }, [client, store, threadId])

  return state
}
