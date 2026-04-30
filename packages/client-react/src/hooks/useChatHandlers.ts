import {
  type Event,
  type ThreadInvitedFrame,
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

export type ChatHandlers = {
  on: {
    message: (fn: EventHandler, opts?: SugarHandlerOptions) => void
    reasoning: (fn: EventHandler, opts?: SugarHandlerOptions) => void
    toolCall: (toolName: string, fn: EventHandler, opts?: SugarHandlerOptions) => void
    toolResult: (fn: EventHandler, opts?: SugarHandlerOptions) => void
    anyEvent: (fn: EventHandler, opts?: SugarHandlerOptions) => void
    invited: (fn: InviteHandler) => void
    event: (eventType: string, fn: EventHandler, opts?: UseHandlerOptions) => void
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

function useInviteSubscription(handler: InviteHandler): void {
  const client = useChatClient()
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  useEffect(() => {
    const off = client.on('thread:invited', (raw: unknown) => {
      const frame = toThreadInvitedFrame(raw as never)
      void handlerRef.current(frame)
    })
    return off
  }, [client])
}

/**
 * Returns the chat event-handler registration namespace.
 *
 * Each `on.X(fn, opts?)` call registers a listener for the corresponding
 * event type and is itself a hook call (uses `useEffect` + a ref to the
 * handler). Call them unconditionally at the top level of your component,
 * just like any other hook.
 *
 * Mirrors Python's `@client.on_message`, `@client.on_tool_call`, etc.
 */
export function useChatHandlers(): ChatHandlers {
  return {
    on: {
      message: (fn, opts = {}) =>
        useEventSubscription('message', fn, { allEvents: opts.allEvents }),
      reasoning: (fn, opts = {}) =>
        useEventSubscription('reasoning', fn, { allEvents: opts.allEvents }),
      toolCall: (toolName, fn, opts = {}) =>
        useEventSubscription('tool.call', fn, { toolName, allEvents: opts.allEvents }),
      toolResult: (fn, opts = {}) =>
        useEventSubscription('tool.result', fn, { allEvents: opts.allEvents }),
      anyEvent: (fn, opts = {}) =>
        useEventSubscription('*', fn, { allEvents: opts.allEvents }),
      invited: (fn) => useInviteSubscription(fn),
      event: (eventType, fn, opts = {}) => useEventSubscription(eventType, fn, opts),
    },
  }
}
