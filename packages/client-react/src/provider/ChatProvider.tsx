import type {
  StreamDeltaFrameWire,
  StreamEndFrameWire,
  StreamStartFrameWire,
} from '@rfnry/chat-protocol'
import {
  type Identity,
  parsePresenceJoinedFrame,
  parsePresenceLeftFrame,
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
import { createPresenceSlice } from '../store/presence'
import {
  ChatContext,
  type ChatContextValue,
  type EventListener,
  type EventRegistry,
} from './ChatContext'

export type ChatProviderProps = ChatClientOptions & {
  children: ReactNode
  queryClient?: QueryClient
  fallback?: ReactNode
  errorFallback?: ReactNode

  onThreadInvited?: (thread: Thread, addedBy: Identity) => void

  autoJoinOnInvite?: boolean
}

export function identitiesEqual(a?: Identity | null, b?: Identity | null): boolean {
  if (a === b) return true
  if (a == null || b == null) return a == null && b == null
  return a.id === b.id && a.role === b.role && a.name === b.name
}

export function ChatProvider(props: ChatProviderProps) {
  const {
    children,
    queryClient: externalQc,
    fallback,
    errorFallback,
    onThreadInvited,
    autoJoinOnInvite = true,
    ...clientOpts
  } = props
  const optsRef = useRef(clientOpts)
  const onThreadInvitedRef = useRef(onThreadInvited)
  onThreadInvitedRef.current = onThreadInvited
  const autoJoinRef = useRef(autoJoinOnInvite)
  autoJoinRef.current = autoJoinOnInvite
  const [value, setValue] = useState<ChatContextValue | null>(null)
  const [failed, setFailed] = useState(false)
  const qcRef = useRef<QueryClient>(
    externalQc ??
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      })
  )
  const clientRef = useRef<ChatClient | null>(null)
  const lastOptsRef = useRef({ url: clientOpts.url, identity: clientOpts.identity ?? null })

  useEffect(() => {
    const callerOnReconnectFailed = optsRef.current.onReconnectFailed
    const clientOpts = {
      ...optsRef.current,
      onReconnectFailed: () => {
        setFailed(true)
        callerOnReconnectFailed?.()
      },
    }
    const client = new ChatClient(clientOpts)
    const store = createChatStore()
    const presence = createPresenceSlice()
    clientRef.current = client
    const disposers: Array<() => void> = []

    let cancelled = false
    const setup = async () => {
      store.getState().actions.setConnectionStatus('connecting')
      try {
        await client.connect()
        if (cancelled) return
        store.getState().actions.setConnectionStatus('connected')

        const eventListeners = new Set<EventListener>()
        const eventRegistry: EventRegistry = {
          subscribe(listener) {
            eventListeners.add(listener)
            return () => {
              eventListeners.delete(listener)
            }
          },
        }

        disposers.push(
          client.on('event', (data) => {
            const event = toEvent(data as never)
            store.getState().actions.addEvent(event)

            for (const listener of [...eventListeners]) {
              try {
                listener(event)
              } catch (err) {
                console.error('[rfnry] handler error for event type "%s":', event.type, err)
              }
            }
          })
        )
        disposers.push(
          client.on('run:updated', (data) => {
            store.getState().actions.upsertRun(toRun(data as never))
          })
        )
        disposers.push(
          client.on('thread:updated', (data) => {
            store.getState().actions.setThreadMeta(toThread(data as never))
          })
        )
        disposers.push(
          client.on('members:updated', (data) => {
            const payload = data as { thread_id: string; members: unknown[] }
            const identities = payload.members.map((m) => toIdentity(m as never))
            store.getState().actions.setMembers(payload.thread_id, identities)
          })
        )
        disposers.push(
          client.on('thread:invited', (data) => {
            const frame = toThreadInvitedFrame(data as never)
            store.getState().actions.setThreadMeta(frame.thread)
            if (autoJoinRef.current) {
              void client.joinThread(frame.thread.id).catch(() => {})
            }
            qcRef.current.invalidateQueries({ queryKey: ['chat', 'threads'] })
            onThreadInvitedRef.current?.(frame.thread, frame.addedBy)
          })
        )
        disposers.push(
          client.on('thread:cleared', (data) => {
            const payload = data as { thread_id: string }
            if (typeof payload?.thread_id === 'string') {
              store.getState().actions.clearThreadEvents(payload.thread_id)
            }
          })
        )
        disposers.push(
          client.on('thread:created', (data) => {
            const thread = toThread(data as never)
            store.getState().actions.setThreadMeta(thread)
            qcRef.current.invalidateQueries({ queryKey: ['chat', 'threads'] })
          })
        )
        disposers.push(
          client.on('thread:deleted', (data) => {
            const payload = data as { thread_id: string }
            if (typeof payload?.thread_id === 'string') {
              store.getState().actions.clearThreadEvents(payload.thread_id)
              qcRef.current.invalidateQueries({ queryKey: ['chat', 'threads'] })
            }
          })
        )
        disposers.push(
          client.on('stream:start', (data) => {
            const frame = data as StreamStartFrameWire
            store.getState().actions.beginStream({
              eventId: frame.event_id,
              threadId: frame.thread_id,
              runId: frame.run_id,
              author: toIdentity(frame.author),
              targetType: frame.target_type,
            })
          })
        )
        disposers.push(
          client.on('stream:delta', (data) => {
            const frame = data as StreamDeltaFrameWire
            store.getState().actions.appendStreamDelta(frame.event_id, frame.text)
          })
        )
        disposers.push(
          client.on('stream:end', (data) => {
            const frame = data as StreamEndFrameWire
            store.getState().actions.endStream(frame.event_id)
          })
        )

        disposers.push(
          client.on('presence:joined', (data) => {
            presence.applyJoined(parsePresenceJoinedFrame(data))
          })
        )
        disposers.push(
          client.on('presence:left', (data) => {
            presence.applyLeft(parsePresenceLeftFrame(data))
          })
        )

        setValue({ client, store, events: eventRegistry, presence })

        void client
          .listPresence()
          .then((snapshot) => {
            if (cancelled) return
            presence.hydrate(snapshot)
          })
          .catch((err) => {
            console.warn('[rfnry] failed to hydrate presence:', err)
          })
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
      clientRef.current = null
    }
  }, [])

  useEffect(() => {
    const last = lastOptsRef.current
    const nextIdentity = clientOpts.identity ?? null
    if (clientOpts.url === last.url && identitiesEqual(nextIdentity, last.identity)) {
      return
    }
    lastOptsRef.current = { url: clientOpts.url, identity: nextIdentity }

    const client = clientRef.current
    const currentValue = value
    if (!client || !currentValue) return

    const store = currentValue.store
    store.getState().actions.reset()
    qcRef.current.invalidateQueries({ queryKey: ['chat'] })

    void (async () => {
      store.getState().actions.setConnectionStatus('connecting')
      try {
        await client.reconnect({ url: clientOpts.url, identity: nextIdentity })
        store.getState().actions.setConnectionStatus('connected')
      } catch {
        store.getState().actions.setConnectionStatus('disconnected')
      }
    })()
  }, [clientOpts.url, clientOpts.identity, value])

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
