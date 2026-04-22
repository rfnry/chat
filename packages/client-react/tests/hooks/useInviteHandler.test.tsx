import type { ThreadInvitedFrame } from '@rfnry/chat-protocol'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useInviteHandler } from '../../src/hooks/useInviteHandler'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function harness(client: Partial<ChatClient>) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider value={{ client: client as ChatClient, store: createChatStore() }}>
      {children}
    </ChatContext.Provider>
  )
}

function Probe({ onFrame }: { onFrame: (frame: ThreadInvitedFrame) => void }) {
  useInviteHandler(onFrame)
  return null
}

describe('useInviteHandler', () => {
  it('receives the full parsed ThreadInvitedFrame including addedMember', async () => {
    let raw: ((data: unknown) => void) | null = null
    const off = vi.fn()
    const client = {
      on: vi.fn((event: string, handler: (data: unknown) => void) => {
        expect(event).toBe('thread:invited')
        raw = handler
        return off
      }),
    }

    const received: ThreadInvitedFrame[] = []
    const Wrapper = harness(client)
    const view = render(
      <Wrapper>
        <Probe onFrame={(f) => received.push(f)} />
      </Wrapper>
    )

    await waitFor(() => expect(raw).not.toBeNull())

    raw!({
      thread: {
        id: 'th_invited',
        tenant: {},
        metadata: { title: 'Proactive ping' },
        created_at: '2026-04-21T00:00:00Z',
        updated_at: '2026-04-21T00:00:00Z',
      },
      added_member: { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} },
      added_by: { role: 'assistant', id: 'a_bot', name: 'Bot', metadata: {} },
    })

    await waitFor(() => expect(received).toHaveLength(1))
    const frame = received[0]!
    expect(frame.thread.id).toBe('th_invited')
    expect(frame.thread.metadata).toMatchObject({ title: 'Proactive ping' })
    // The key point: addedMember is delivered (the lossy `onThreadInvited`
    // prop drops it).
    expect(frame.addedMember.id).toBe('u_alice')
    expect(frame.addedMember.name).toBe('Alice')
    expect(frame.addedBy.id).toBe('a_bot')
    expect(frame.addedBy.role).toBe('assistant')

    view.unmount()
    expect(off).toHaveBeenCalled()
  })

  it('keeps the latest handler reference across re-renders without re-subscribing', async () => {
    let raw: ((data: unknown) => void) | null = null
    const onSpy = vi.fn((_event: string, handler: (data: unknown) => void) => {
      raw = handler
      return () => {}
    })
    const client = { on: onSpy }

    const first = vi.fn()
    const second = vi.fn()

    const Wrapper = harness(client)
    const { rerender } = render(
      <Wrapper>
        <Probe onFrame={first} />
      </Wrapper>
    )
    await waitFor(() => expect(raw).not.toBeNull())
    const subscriptionsAfterMount = onSpy.mock.calls.length

    rerender(
      <Wrapper>
        <Probe onFrame={second} />
      </Wrapper>
    )

    // No re-subscription just because the handler identity changed.
    expect(onSpy.mock.calls.length).toBe(subscriptionsAfterMount)

    raw!({
      thread: {
        id: 'th_invited',
        tenant: {},
        metadata: {},
        created_at: '2026-04-21T00:00:00Z',
        updated_at: '2026-04-21T00:00:00Z',
      },
      added_member: { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} },
      added_by: { role: 'assistant', id: 'a_bot', name: 'Bot', metadata: {} },
    })

    await waitFor(() => expect(second).toHaveBeenCalledTimes(1))
    expect(first).not.toHaveBeenCalled()
  })
})
