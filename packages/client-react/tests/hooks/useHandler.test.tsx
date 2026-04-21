import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useHandler, useToolCallHandler } from '../../src/hooks/useHandler'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function harness(client: Partial<ChatClient>) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider value={{ client: client as ChatClient, store: createChatStore() }}>
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
    let raw: ((data: unknown) => void) | null = null
    const off = vi.fn()
    const client = {
      on: vi.fn((_event: string, handler: (data: unknown) => void) => {
        raw = handler
        return off
      }),
    }

    const received: unknown[] = []
    const Wrapper = harness(client)
    const view = render(
      <Wrapper>
        <MessageProbe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )

    await waitFor(() => expect(raw).not.toBeNull())

    raw!({
      id: 'evt_1',
      thread_id: 't_1',
      type: 'message',
      author: { role: 'user', id: 'u1', name: 'U', metadata: {} },
      created_at: '2026-04-10T00:00:00Z',
      metadata: {},
      content: [{ type: 'text', text: 'hi' }],
    })

    await waitFor(() => expect(received.length).toBeGreaterThan(0))
    expect((received[0] as { type: string }).type).toBe('message')

    view.unmount()
    expect(off).toHaveBeenCalled()
  })

  it('ignores events whose type does not match', async () => {
    let raw: ((data: unknown) => void) | null = null
    const client = {
      on: vi.fn((_event: string, handler: (data: unknown) => void) => {
        raw = handler
        return () => {}
      }),
    }
    const received: unknown[] = []
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <MessageProbe onEvent={(e) => received.push(e)} />
      </Wrapper>
    )
    await waitFor(() => expect(raw).not.toBeNull())
    raw!({
      id: 'evt_2',
      thread_id: 't_1',
      type: 'reasoning',
      author: { role: 'user', id: 'u1', name: 'U', metadata: {} },
      created_at: '2026-04-10T00:00:00Z',
      metadata: {},
      content: 'thinking',
    })
    await new Promise((r) => setTimeout(r, 10))
    expect(received).toEqual([])
  })

  it('useToolCallHandler filters by tool.name', async () => {
    let raw: ((data: unknown) => void) | null = null
    const client = {
      on: vi.fn((_event: string, handler: (data: unknown) => void) => {
        raw = handler
        return () => {}
      }),
    }
    const stock: unknown[] = []
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <ToolProbe onEvent={(e) => stock.push(e)} />
      </Wrapper>
    )
    await waitFor(() => expect(raw).not.toBeNull())

    const base = {
      thread_id: 't_1',
      author: { role: 'user', id: 'u1', name: 'U', metadata: {} },
      created_at: '2026-04-10T00:00:00Z',
      metadata: {},
      type: 'tool.call',
    }
    raw!({ ...base, id: 'e1', tool: { id: 'c1', name: 'get_weather', arguments: {} } })
    raw!({ ...base, id: 'e2', tool: { id: 'c2', name: 'get_stock', arguments: {} } })

    await waitFor(() => expect(stock.length).toBe(1))
    expect((stock[0] as { tool: { name: string } }).tool.name).toBe('get_stock')
  })
})
