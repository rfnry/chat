import type { Event } from '@rfnry/chat-protocol'
import { toEvent } from '@rfnry/chat-protocol'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useHandler, useToolCallHandler } from '../../src/hooks/useHandler'
import type { EventListener, EventRegistry } from '../../src/provider/ChatContext'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function makeEventRegistry(): {
  registry: EventRegistry
  dispatch: (event: Event) => void
  unsubscribeSpy: ReturnType<typeof vi.fn>
} {
  const listeners = new Set<EventListener>()
  const unsubscribeSpy = vi.fn()
  const registry: EventRegistry = {
    subscribe(listener) {
      listeners.add(listener)
      return () => {
        unsubscribeSpy()
        listeners.delete(listener)
      }
    },
  }
  const dispatch = (event: Event) => {
    for (const l of listeners) l(event)
  }
  return { registry, dispatch, unsubscribeSpy }
}

function harness(client: Partial<ChatClient>, events: EventRegistry) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider
      value={{ client: client as ChatClient, store: createChatStore(), events }}
    >
      {children}
    </ChatContext.Provider>
  )
}

function MessageProbe({ onEvent }: { onEvent: (e: unknown) => void }) {
  useHandler('message', onEvent)
  return null
}

function ToolProbe({ onEvent }: { onEvent: (e: unknown) => void }) {
  useToolCallHandler('get_stock', onEvent)
  return null
}

describe('useHandler', () => {
  it('fires for events matching the registered type', async () => {
    const { registry, dispatch, unsubscribeSpy } = makeEventRegistry()
    const client = { identity: null }

    const received: unknown[] = []
    const Wrapper = harness(client, registry)
    const view = render(
      <Wrapper>
        <MessageProbe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )

    // Give the useEffect time to register
    await new Promise((r) => setTimeout(r, 0))

    dispatch(
      toEvent({
        id: 'evt_1',
        thread_id: 't_1',
        type: 'message',
        author: { role: 'user', id: 'u1', name: 'U', metadata: {} },
        created_at: '2026-04-10T00:00:00Z',
        metadata: {},
        content: [{ type: 'text', text: 'hi' }],
      } as never)
    )

    await waitFor(() => expect(received.length).toBeGreaterThan(0))
    expect((received[0] as { type: string }).type).toBe('message')

    view.unmount()
    expect(unsubscribeSpy).toHaveBeenCalled()
  })

  it('ignores events whose type does not match', async () => {
    const { registry, dispatch } = makeEventRegistry()
    const client = { identity: null }
    const received: unknown[] = []
    const Wrapper = harness(client, registry)
    render(
      <Wrapper>
        <MessageProbe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await new Promise((r) => setTimeout(r, 0))
    dispatch(
      toEvent({
        id: 'evt_2',
        thread_id: 't_1',
        type: 'reasoning',
        author: { role: 'user', id: 'u1', name: 'U', metadata: {} },
        created_at: '2026-04-10T00:00:00Z',
        metadata: {},
        content: 'thinking',
      } as never)
    )
    await new Promise((r) => setTimeout(r, 10))
    expect(received).toEqual([])
  })

  it('useToolCallHandler filters by tool.name', async () => {
    const { registry, dispatch } = makeEventRegistry()
    const client = { identity: null }
    const stock: unknown[] = []
    const Wrapper = harness(client, registry)
    render(
      <Wrapper>
        <ToolProbe onEvent={(e) => stock.push(e)} />
      </Wrapper>
    )
    await new Promise((r) => setTimeout(r, 0))

    const base = {
      thread_id: 't_1',
      author: { role: 'user', id: 'u1', name: 'U', metadata: {} },
      created_at: '2026-04-10T00:00:00Z',
      metadata: {},
      type: 'tool.call',
    }
    dispatch(
      toEvent({
        ...base,
        id: 'e1',
        tool: { id: 'c1', name: 'get_weather', arguments: {} },
      } as never)
    )
    dispatch(
      toEvent({ ...base, id: 'e2', tool: { id: 'c2', name: 'get_stock', arguments: {} } } as never)
    )

    await waitFor(() => expect(stock.length).toBe(1))
    expect((stock[0] as { tool: { name: string } }).tool.name).toBe('get_stock')
  })
})
