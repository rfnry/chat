import {
  type Identity,
  type Thread,
  toEvent,
  toIdentity,
  toRun,
  toThread,
  toThreadInvitedFrame,
} from '@rfnry/chat-protocol'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { ChatClient, type ChatClientOptions } from '../client'
import { createChatStore } from '../store/chatStore'
import { ChatContext, type ChatContextValue } from './ChatContext'

export type ChatProviderProps = ChatClientOptions & {
  children: ReactNode
  queryClient?: QueryClient
  fallback?: ReactNode
  errorFallback?: ReactNode
  onThreadInvited?: (thread: Thread, addedBy: Identity) => void
}

export function ChatProvider(props: ChatProviderProps) {
  const {
    children,
    queryClient: externalQc,
    fallback,
    errorFallback,
    onThreadInvited,
    ...clientOpts
  } = props
  const optsRef = useRef(clientOpts)
  const onThreadInvitedRef = useRef(onThreadInvited)
  onThreadInvitedRef.current = onThreadInvited
  const [value, setValue] = useState<ChatContextValue | null>(null)
  const [failed, setFailed] = useState(false)
  const qcRef = useRef<QueryClient>(externalQc ?? new QueryClient())

  useEffect(() => {
    const client = new ChatClient(optsRef.current)
    const store = createChatStore()
    const disposers: Array<() => void> = []

    let cancelled = false
    const setup = async () => {
      store.getState().actions.setConnectionStatus('connecting')
      try {
        await client.connect()
        if (cancelled) return
        store.getState().actions.setConnectionStatus('connected')

        disposers.push(
          client.on('event', (data) => {
            store.getState().actions.addEvent(toEvent(data as never))
          }),
        )
        disposers.push(
          client.on('run:updated', (data) => {
            store.getState().actions.upsertRun(toRun(data as never))
          }),
        )
        disposers.push(
          client.on('thread:updated', (data) => {
            store.getState().actions.setThreadMeta(toThread(data as never))
          }),
        )
        disposers.push(
          client.on('members:updated', (data) => {
            const payload = data as { thread_id: string; members: unknown[] }
            const identities = payload.members.map((m) => toIdentity(m as never))
            store.getState().actions.setMembers(payload.thread_id, identities)
          }),
        )
        disposers.push(
          client.on('thread:invited', (data) => {
            const frame = toThreadInvitedFrame(data as never)
            store.getState().actions.setThreadMeta(frame.thread)
            void client.joinThread(frame.thread.id).catch(() => {})
            qcRef.current.invalidateQueries({ queryKey: ['chat', 'threads'] })
            onThreadInvitedRef.current?.(frame.thread, frame.addedBy)
          }),
        )

        setValue({ client, store })
      } catch {
        if (cancelled) return
        store.getState().actions.setConnectionStatus('disconnected')
        setFailed(true)
      }
    }
    void setup()

    return () => {
      cancelled = true
      for (const dispose of disposers) dispose()
      void client.disconnect()
      store.getState().actions.reset()
    }
  }, [])

  let body: ReactNode
  if (value) {
    body = <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
  } else if (failed) {
    body = errorFallback ?? null
  } else {
    body = fallback ?? null
  }
  return <QueryClientProvider client={qcRef.current}>{body}</QueryClientProvider>
}
