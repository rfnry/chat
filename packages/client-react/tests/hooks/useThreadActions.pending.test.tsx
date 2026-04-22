import { act, render, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ChatClient } from '../../src/client'
import { useThreadActions } from '../../src/hooks/useThreadActions'
import { ChatContext } from '../../src/provider/ChatContext'
import { createChatStore } from '../../src/store/chatStore'

function harness(client: ChatClient) {
  return ({ children }: { children: ReactNode }) => (
    <ChatContext.Provider value={{ client, store: createChatStore() }}>
      {children}
    </ChatContext.Provider>
  )
}

function Probe({
  onState,
}: {
  onState: (state: { isPending: boolean; actions: ReturnType<typeof useThreadActions> }) => void
}) {
  const actions = useThreadActions('th_1')
  onState({ isPending: actions.isPending, actions })
  return <div data-testid="pending">{String(actions.isPending)}</div>
}

describe('useThreadActions isPending', () => {
  it('starts false, flips true during send, then false after resolve', async () => {
    let resolveSend: ((event: unknown) => void) | null = null
    const client = {
      sendMessage: vi.fn(
        () =>
          new Promise((resolve) => {
            resolveSend = resolve as (event: unknown) => void
          })
      ),
    } as unknown as ChatClient
    const Wrapper = harness(client)
    const states: boolean[] = []
    let latest: ReturnType<typeof useThreadActions> | null = null

    const { getByTestId } = render(
      <Wrapper>
        <Probe
          onState={({ isPending, actions }) => {
            states.push(isPending)
            latest = actions
          }}
        />
      </Wrapper>
    )

    expect(getByTestId('pending').textContent).toBe('false')

    let sendPromise: Promise<unknown> | null = null
    act(() => {
      sendPromise = latest!.send({
        clientId: 'c1',
        content: [{ type: 'text', text: 'hi' }],
      })
    })

    await waitFor(() => {
      expect(getByTestId('pending').textContent).toBe('true')
    })

    await act(async () => {
      resolveSend!({
        id: 'evt_1',
        threadId: 'th_1',
        type: 'message',
        author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
        createdAt: '2026-04-10T00:00:00Z',
        metadata: {},
        content: [],
      })
      await sendPromise
    })

    await waitFor(() => {
      expect(getByTestId('pending').textContent).toBe('false')
    })
    expect(states.at(0)).toBe(false)
    expect(states.includes(true)).toBe(true)
    expect(states.at(-1)).toBe(false)
  })

  it('flips false again after a rejected send', async () => {
    let rejectSend: ((err: Error) => void) | null = null
    const client = {
      sendMessage: vi.fn(
        () =>
          new Promise((_, reject) => {
            rejectSend = reject
          })
      ),
    } as unknown as ChatClient
    const Wrapper = harness(client)
    let latest: ReturnType<typeof useThreadActions> | null = null

    const { getByTestId } = render(
      <Wrapper>
        <Probe
          onState={({ actions }) => {
            latest = actions
          }}
        />
      </Wrapper>
    )

    const caught: { err: Error | null } = { err: null }
    let sendPromise: Promise<unknown> | null = null
    act(() => {
      sendPromise = latest!
        .send({
          clientId: 'c1',
          content: [{ type: 'text', text: 'hi' }],
        })
        .catch((err: Error) => {
          caught.err = err
        })
    })

    await waitFor(() => {
      expect(getByTestId('pending').textContent).toBe('true')
    })

    await act(async () => {
      rejectSend!(new Error('boom'))
      await sendPromise
    })

    await waitFor(() => {
      expect(getByTestId('pending').textContent).toBe('false')
    })
    expect(caught.err?.message).toBe('boom')
  })

  it('keeps action callback identity stable across isPending toggles (R18)', async () => {
    const client = {
      sendMessage: vi.fn(() => Promise.resolve({ id: 'evt_1' })),
    } as unknown as ChatClient
    const Wrapper = harness(client)

    const { result, rerender } = renderHook(() => useThreadActions('t_A'), {
      wrapper: Wrapper,
    })

    const sendBefore = result.current.send

    await act(async () => {
      await result.current.send({ clientId: 'c1', content: [{ type: 'text', text: 'x' }] })
    })

    rerender()
    const sendAfter = result.current.send

    // R18: send callback identity is preserved across the isPending cycle.
    // Components doing useEffect(..., [actions.send]) should NOT re-fire.
    expect(sendAfter).toBe(sendBefore)
  })
})
