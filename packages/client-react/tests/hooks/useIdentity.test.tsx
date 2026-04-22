import type { Identity, UserIdentity } from '@rfnry/chat-protocol'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

const mockSocket = {
  on: vi.fn(),
  off: vi.fn(),
  once: vi.fn(),
  emit: vi.fn(),
  emitWithAck: vi.fn(),
  disconnect: vi.fn(),
}

vi.mock('socket.io-client', () => ({
  io: vi.fn(() => mockSocket),
}))

import { ChatClient } from '../../src/client'
import { useIdentity } from '../../src/hooks/useChatClient'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function harness(client: ChatClient) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider value={{ client, store: createChatStore() }}>
      {children}
    </ChatContext.Provider>
  )
}

describe('ChatClient.identity + useIdentity()', () => {
  const me: UserIdentity = {
    role: 'user',
    id: 'u_42',
    name: 'Alice',
    metadata: {},
  }

  it('stores the configured identity on the client', () => {
    const client = new ChatClient({ url: 'http://localhost:8000', identity: me })
    expect(client.identity).toEqual(me)
  })

  it('defaults identity to null when none supplied', () => {
    const client = new ChatClient({ url: 'http://localhost:8000' })
    expect(client.identity).toBeNull()
  })

  it('useIdentity returns the client identity through context', () => {
    const client = new ChatClient({ url: 'http://localhost:8000', identity: me })
    let seen: Identity | null | undefined
    function Probe() {
      seen = useIdentity()
      return null
    }
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(seen).toEqual(me)
  })

  it('useIdentity returns null when client was built without an identity', () => {
    const client = new ChatClient({ url: 'http://localhost:8000' })
    let seen: Identity | null | undefined
    function Probe() {
      seen = useIdentity()
      return null
    }
    const Wrapper = harness(client)
    render(
      <Wrapper>
        <Probe />
      </Wrapper>
    )
    expect(seen).toBeNull()
  })
})
