import type { Event } from '@rfnry/chat-protocol'
import { toEvent } from '@rfnry/chat-protocol'
import { useEffect, useRef } from 'react'
import { useChatClient } from './useChatClient'

export type EventHandler = (event: Event) => void | Promise<void>

export type UseHandlerOptions = {
  toolName?: string
  /**
   * When true, deliver every matching event — including ones authored by the
   * connected identity and ones whose `recipients` list excludes this identity.
   * When false or omitted (default), self-authored and mismatched-recipient
   * events are skipped, mirroring the Python Dispatcher's default filters.
   * If the client has no configured identity, both filters are inert.
   */
  allEvents?: boolean
}

export type SugarHandlerOptions = {
  allEvents?: boolean
}

function passesDefaultFilters(event: Event, selfId: string): boolean {
  if (event.author.id === selfId) return false
  if (event.recipients !== null && !event.recipients.includes(selfId)) return false
  return true
}

export function useHandler(
  eventType: string,
  handler: EventHandler,
  options: UseHandlerOptions = {}
): void {
  const client = useChatClient()
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  const allEvents = options.allEvents ?? false

  useEffect(() => {
    const off = client.on('event', (raw: unknown) => {
      const event = toEvent(raw as never)
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
    })
    return off
  }, [client, eventType, options.toolName, allEvents])
}

export function useMessageHandler(handler: EventHandler, options: SugarHandlerOptions = {}): void {
  useHandler('message', handler, { allEvents: options.allEvents })
}

export function useReasoningHandler(
  handler: EventHandler,
  options: SugarHandlerOptions = {}
): void {
  useHandler('reasoning', handler, { allEvents: options.allEvents })
}

export function useToolCallHandler(
  toolName: string,
  handler: EventHandler,
  options: SugarHandlerOptions = {}
): void {
  useHandler('tool.call', handler, { toolName, allEvents: options.allEvents })
}

export function useToolResultHandler(
  handler: EventHandler,
  options: SugarHandlerOptions = {}
): void {
  useHandler('tool.result', handler, { allEvents: options.allEvents })
}

export function useAnyEventHandler(handler: EventHandler, options: SugarHandlerOptions = {}): void {
  useHandler('*', handler, { allEvents: options.allEvents })
}
