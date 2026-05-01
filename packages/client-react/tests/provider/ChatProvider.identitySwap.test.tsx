import type { Identity } from '@rfnry/chat-protocol'
import { render, waitFor } from '@testing-library/react'
import { useContext } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { socketOn, socketOnce, socketDisconnect } = vi.hoisted(() => ({
  socketOn: vi.fn(),
  socketOnce: vi.fn(),
  socketDisconnect: vi.fn(),
}))

vi.mock('socket.io-client', () => ({
  io: vi.fn(() => ({
    on: socketOn,
    off: vi.fn(),
    once: (event: string, cb: (...args: unknown[]) => void) => {
      socketOnce(event, cb)
      if (event === 'connect') queueMicrotask(() => cb())
    },
    disconnect: socketDisconnect,
    emitWithAck: vi.fn(),
  })),
}))

import { ChatContext, type ChatContextValue } from '../../src/provider/ChatContext'
import { ChatProvider } from '../../src/provider/ChatProvider'

function CtxProbe({ onCtx }: { onCtx: (ctx: ChatContextValue) => void }) {
  const ctx = useContext(ChatContext)
  if (ctx) onCtx(ctx)
  return null
}

const ALICE: Identity = { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} }
const BOB: Identity = { role: 'user', id: 'u_bob', name: 'Bob', metadata: {} }

describe('ChatProvider identity-swap reset (Case 4)', () => {
  beforeEach(() => {
    socketOn.mockClear()
    socketOnce.mockClear()
    socketDisconnect.mockClear()
  })

  it('resets store + presence when identity prop changes', async () => {
    let captured: ChatContextValue | null = null
    const { rerender } = render(
      <ChatProvider url="http://x" identity={ALICE} authenticate={async () => ({})}>
        <CtxProbe
          onCtx={(c) => {
            captured = c
          }}
        />
      </ChatProvider>
    )
    await waitFor(() => expect(captured).not.toBeNull())
    const ctx = captured as unknown as ChatContextValue

    ctx.store.getState().actions.setMembers('th_1', [ALICE])
    ctx.presence.hydrate({ members: [ALICE] })
    expect(ctx.store.getState().members.th_1).toHaveLength(1)
    expect(ctx.presence.list()).toHaveLength(1)

    rerender(
      <ChatProvider url="http://x" identity={BOB} authenticate={async () => ({})}>
        <CtxProbe
          onCtx={(c) => {
            captured = c
          }}
        />
      </ChatProvider>
    )

    await waitFor(() => {
      expect(ctx.store.getState().members.th_1 ?? []).toHaveLength(0)
      expect(ctx.presence.list()).toHaveLength(0)
    })
  })

  it('preserves state when resetOnIdentityChange={false}', async () => {
    let captured: ChatContextValue | null = null
    const { rerender } = render(
      <ChatProvider
        url="http://x"
        identity={ALICE}
        authenticate={async () => ({})}
        resetOnIdentityChange={false}
      >
        <CtxProbe
          onCtx={(c) => {
            captured = c
          }}
        />
      </ChatProvider>
    )
    await waitFor(() => expect(captured).not.toBeNull())
    const ctx = captured as unknown as ChatContextValue

    ctx.store.getState().actions.setMembers('th_1', [ALICE])
    ctx.presence.hydrate({ members: [ALICE] })

    rerender(
      <ChatProvider
        url="http://x"
        identity={BOB}
        authenticate={async () => ({})}
        resetOnIdentityChange={false}
      >
        <CtxProbe
          onCtx={(c) => {
            captured = c
          }}
        />
      </ChatProvider>
    )

    // small wait so the effect would have run if it were going to
    await new Promise((r) => setTimeout(r, 10))
    expect(ctx.store.getState().members.th_1).toHaveLength(1)
    expect(ctx.presence.list()).toHaveLength(1)
  })
})
