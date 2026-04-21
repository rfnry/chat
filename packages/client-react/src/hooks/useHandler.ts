import type { Event } from '@rfnry/chat-protocol'
import { toEvent } from '@rfnry/chat-protocol'
import { useEffect, useRef } from 'react'
import { useChatClient } from './useChatClient'

export type EventHandler = (event: Event) => void | Promise<void>

export type UseHandlerOptions = {
  toolName?: string
}

export function useHandler(
  eventType: string,
  handler: EventHandler,
  options: UseHandlerOptions = {}
): void {
  const client = useChatClient()
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  useEffect(() => {
    const off = client.on('event', (raw: unknown) => {
      const event = toEvent(raw as never)
      if (eventType !== '*' && event.type !== eventType) return
      if (options.toolName !== undefined) {
        if (event.type !== 'tool.call') return
        if (event.tool.name !== options.toolName) return
      }
      void handlerRef.current(event)
    })
    return off
  }, [client, eventType, options.toolName])
}

export function useMessageHandler(handler: EventHandler): void {
  useHandler('message', handler)
}

export function useReasoningHandler(handler: EventHandler): void {
  useHandler('reasoning', handler)
}

export function useToolCallHandler(toolName: string, handler: EventHandler): void {
  useHandler('tool.call', handler, { toolName })
}

export function useToolResultHandler(handler: EventHandler): void {
  useHandler('tool.result', handler)
}

export function useAnyEventHandler(handler: EventHandler): void {
  useHandler('*', handler)
}
