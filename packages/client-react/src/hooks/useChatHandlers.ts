import {
  type Event,
  type Identity,
  type PresenceJoinedFrame,
  type PresenceLeftFrame,
  parsePresenceJoinedFrame,
  parsePresenceLeftFrame,
  type Run,
  type Thread,
  type ThreadInvitedFrame,
  toIdentity,
  toRun,
  toThread,
  toThreadInvitedFrame,
} from '@rfnry/chat-protocol'
import { useEffect, useRef } from 'react'
import type { EventListener } from '../provider/ChatContext'
import { useChatClient, useChatEvents } from './useChatClient'

export type EventHandler = (event: Event) => void | Promise<void>

export type SugarHandlerOptions = {
  allEvents?: boolean
}

export type UseHandlerOptions = {
  toolName?: string
  /**
   * When true, deliver every matching event — including self-authored ones
   * and ones whose `recipients` excludes this identity. Mirrors the Python
   * Dispatcher's default-filter opt-out.
   */
  allEvents?: boolean
}

export type InviteHandler = (frame: ThreadInvitedFrame) => void | Promise<void>
export type ThreadUpdatedHandler = (thread: Thread) => void | Promise<void>
export type MembersUpdatedHandler = (threadId: string, members: Identity[]) => void | Promise<void>
export type RunUpdatedHandler = (run: Run) => void | Promise<void>
export type PresenceJoinedHandler = (frame: PresenceJoinedFrame) => void | Promise<void>
export type PresenceLeftHandler = (frame: PresenceLeftFrame) => void | Promise<void>

export type ChatHandlers = {
  on: {
    message: typeof useOnMessage
    reasoning: typeof useOnReasoning
    toolCall: typeof useOnToolCall
    toolResult: typeof useOnToolResult
    anyEvent: typeof useOnAnyEvent
    invited: typeof useOnInvited
    threadUpdated: typeof useOnThreadUpdated
    membersUpdated: typeof useOnMembersUpdated
    runUpdated: typeof useOnRunUpdated
    presenceJoined: typeof useOnPresenceJoined
    presenceLeft: typeof useOnPresenceLeft
    event: typeof useOnEvent
  }
}

function passesDefaultFilters(event: Event, selfId: string): boolean {
  if (event.author.id === selfId) return false
  if (event.recipients !== null && !event.recipients.includes(selfId)) return false
  return true
}

function useEventSubscription(
  eventType: string,
  handler: EventHandler,
  options: UseHandlerOptions = {}
): void {
  const client = useChatClient()
  const events = useChatEvents()
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  const allEvents = options.allEvents ?? false

  useEffect(() => {
    const listener: EventListener = (event) => {
      if (eventType !== '*' && event.type !== eventType) return
      if (options.toolName !== undefined) {
        if (event.type !== 'tool.call') return
        if (event.tool.name !== options.toolName) return
      }
      if (!allEvents) {
        const selfId = client.identity?.id
        if (selfId && !passesDefaultFilters(event, selfId)) return
      }
      void handlerRef.current(event)
    }
    return events.subscribe(listener)
  }, [events, client, eventType, options.toolName, allEvents])
}

function useFrameSubscription<T>(
  socketEvent: string,
  parse: (raw: unknown) => T,
  handler: (parsed: T) => void | Promise<void>
): void {
  const client = useChatClient()
  const handlerRef = useRef(handler)
  handlerRef.current = handler
  const parseRef = useRef(parse)
  parseRef.current = parse

  useEffect(() => {
    const off = client.on(socketEvent, (raw: unknown) => {
      void handlerRef.current(parseRef.current(raw))
    })
    return off
  }, [client, socketEvent])
}

function useOnMessage(fn: EventHandler, opts: SugarHandlerOptions = {}): void {
  useEventSubscription('message', fn, { allEvents: opts.allEvents })
}

function useOnReasoning(fn: EventHandler, opts: SugarHandlerOptions = {}): void {
  useEventSubscription('reasoning', fn, { allEvents: opts.allEvents })
}

function useOnToolCall(toolName: string, fn: EventHandler, opts: SugarHandlerOptions = {}): void {
  useEventSubscription('tool.call', fn, { toolName, allEvents: opts.allEvents })
}

function useOnToolResult(fn: EventHandler, opts: SugarHandlerOptions = {}): void {
  useEventSubscription('tool.result', fn, { allEvents: opts.allEvents })
}

function useOnAnyEvent(fn: EventHandler, opts: SugarHandlerOptions = {}): void {
  useEventSubscription('*', fn, { allEvents: opts.allEvents })
}

function useOnInvited(fn: InviteHandler): void {
  useFrameSubscription('thread:invited', (raw) => toThreadInvitedFrame(raw as never), fn)
}

function useOnThreadUpdated(fn: ThreadUpdatedHandler): void {
  useFrameSubscription('thread:updated', (raw) => toThread(raw as never), fn)
}

function useOnMembersUpdated(fn: MembersUpdatedHandler): void {
  const client = useChatClient()
  const handlerRef = useRef(fn)
  handlerRef.current = fn

  useEffect(() => {
    const off = client.on('members:updated', (raw: unknown) => {
      const payload = raw as { thread_id: string; members: unknown[] }
      const identities = payload.members.map((m) => toIdentity(m as never))
      void handlerRef.current(payload.thread_id, identities)
    })
    return off
  }, [client])
}

function useOnRunUpdated(fn: RunUpdatedHandler): void {
  useFrameSubscription('run:updated', (raw) => toRun(raw as never), fn)
}

function useOnPresenceJoined(fn: PresenceJoinedHandler): void {
  useFrameSubscription('presence:joined', parsePresenceJoinedFrame, fn)
}

function useOnPresenceLeft(fn: PresenceLeftHandler): void {
  useFrameSubscription('presence:left', parsePresenceLeftFrame, fn)
}

function useOnEvent(eventType: string, fn: EventHandler, opts: UseHandlerOptions = {}): void {
  useEventSubscription(eventType, fn, opts)
}

const HANDLER_NAMESPACE: ChatHandlers = {
  on: {
    message: useOnMessage,
    reasoning: useOnReasoning,
    toolCall: useOnToolCall,
    toolResult: useOnToolResult,
    anyEvent: useOnAnyEvent,
    invited: useOnInvited,
    threadUpdated: useOnThreadUpdated,
    membersUpdated: useOnMembersUpdated,
    runUpdated: useOnRunUpdated,
    presenceJoined: useOnPresenceJoined,
    presenceLeft: useOnPresenceLeft,
    event: useOnEvent,
  },
}

/**
 * Returns the chat event-handler registration namespace.
 *
 * Each `on.X(fn, opts?)` call registers a listener for the corresponding
 * event type and is itself a hook call (uses `useEffect` + a ref to the
 * handler). Call them unconditionally at the top level of your component,
 * just like any other hook.
 *
 * Mirrors Python's `@client.on_message`, `@client.on_tool_call`,
 * `@client.on_thread_updated`, `@client.on_members_updated`,
 * `@client.on_run_updated`, `@client.on_presence_joined`,
 * `@client.on_presence_left`, etc.
 */
export function useChatHandlers(): ChatHandlers {
  return HANDLER_NAMESPACE
}
