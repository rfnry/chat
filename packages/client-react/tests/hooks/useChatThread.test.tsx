import { act, render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useChatThread } from '../../src/hooks/useChatThread'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

import { createPresenceSlice } from '../../src/store/presence'

const fakeThread = {
  id: 'th_1',
  tenant: { org: 'A' },
  metadata: { title: 'First' },
  createdAt: '2026-04-10T00:00:00Z',
  updatedAt: '2026-04-10T00:00:00Z',
}

function Probe() {
  const t = useChatThread('th_1')
  return <div data-testid="title">{t ? String(t.metadata.title ?? '') : 'none'}</div>
}

describe('useChatThread', () => {
  it('returns null when no thread is in the store', () => {
    const store = createChatStore()
    const { getByTestId } = render(
      <ChatContext.Provider
        value={{
          client: {} as ChatClient,
          store,
          events: { subscribe: () => () => {} },
          presence: createPresenceSlice(),
        }}
      >
        <Probe />
      </ChatContext.Provider>
    )
    expect(getByTestId('title').textContent).toBe('none')
  })

  it('reflects store updates', () => {
    const store = createChatStore()
    const { getByTestId } = render(
      <ChatContext.Provider
        value={{
          client: {} as ChatClient,
          store,
          events: { subscribe: () => () => {} },
          presence: createPresenceSlice(),
        }}
      >
        <Probe />
      </ChatContext.Provider>
    )

    act(() => {
      store.getState().actions.setThreadMeta(fakeThread)
    })
    expect(getByTestId('title').textContent).toBe('First')

    act(() => {
      store.getState().actions.setThreadMeta({ ...fakeThread, metadata: { title: 'Renamed' } })
    })
    expect(getByTestId('title').textContent).toBe('Renamed')
  })
})
