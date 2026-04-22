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
  /**
   * Convenience callback for the common "someone added me to a thread" case.
   * Receives only `(thread, addedBy)` — the invitee identity is implicit (it's
   * the connected user). If you need the full frame including `addedMember`
   * (e.g. for group-chat invites where you care which user was added), use
   * the `useInviteHandler` hook instead.
   */
  onThreadInvited?: (thread: Thread, addedBy: Identity) => void
  /**
   * When a `thread:invited` frame arrives, automatically call
   * `client.joinThread(frame.thread.id)` so live event delivery starts
   * immediately. Defaults to `true`, mirroring Python's
   * `auto_join_on_invite=True`. Set to `false` if you want to inspect the
   * frame first (via `useInviteHandler` or `client.on('thread:invited',
   * ...)`) and decide whether to join.
   */
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
  const qcRef = useRef<QueryClient>(externalQc ?? new QueryClient())
  const clientRef = useRef<ChatClient | null>(null)
  const lastOptsRef = useRef({ url: clientOpts.url, identity: clientOpts.identity ?? null })

  useEffect(() => {
    const client = new ChatClient(optsRef.current)
    const store = createChatStore()
    clientRef.current = client
    const disposers: Array<() => void> = []

    let cancelled = false
    const setup = async () => {
      store.getState().actions.setConnectionStatus('connecting')
      try {
        await client.connect()
        if (cancelled) return
        store.getState().actions.setConnectionStatus('connected')

        // Per-thread event subscribers. The provider parses each incoming
        // `event` frame ONCE and dispatches the typed Event to all listeners.
        // Mounted handler hooks subscribe here instead of calling client.on('event')
        // independently — at N mounted hooks, this drops parse calls from N+1
        // to 1 per incoming event.
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
            for (const listener of eventListeners) {
              try {
                listener(event)
              } catch (err) {
                console.error('handler error', err)
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

        setValue({ client, store, events: eventRegistry })
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

  // Reactive reconnect: when url or identity change after initial mount, swap
  // identity on the existing client via `client.reconnect()` instead of letting
  // the consumer force a full remount via `key`. This keeps a single socket
  // per tab for its lifetime, even across role/workspace switches — old
  // sockets never stack up on the server. Listeners are re-registered
  // automatically by the client inside reconnect().
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
