import { QueryClient, useQueryClient } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChatProvider } from '../../src/provider/ChatProvider'

vi.mock('../../src/client', () => ({
  ChatClient: class {
    connect = vi.fn().mockResolvedValue(undefined)
    disconnect = vi.fn()
    on = vi.fn(() => () => {})
    listPresence = vi.fn().mockResolvedValue({ members: [] })
  },
}))

function Probe({ onResolve }: { onResolve: (qc: QueryClient) => void }) {
  onResolve(useQueryClient())
  return null
}

describe('ChatProvider QueryClient fallback', () => {
  it('uses tightened defaults when caller provides none', async () => {
    let captured: QueryClient | undefined
    render(
      <ChatProvider
        url="http://test"
        identity={{ id: 'u_x', role: 'user', name: 'x', metadata: {} }}
      >
        <Probe
          onResolve={(qc) => {
            captured = qc
          }}
        />
      </ChatProvider>
    )

    await waitFor(() => expect(captured).toBeDefined())
    const opts = captured!.getDefaultOptions().queries
    expect(opts?.staleTime).toBe(30_000)
    expect(opts?.retry).toBe(1)
    expect(opts?.refetchOnWindowFocus).toBe(false)
  })

  it('does not override a caller-supplied QueryClient', async () => {
    const external = new QueryClient({ defaultOptions: { queries: { staleTime: 7_777 } } })
    let captured: QueryClient | undefined
    render(
      <ChatProvider
        url="http://test"
        identity={{ id: 'u_x', role: 'user', name: 'x', metadata: {} }}
        queryClient={external}
      >
        <Probe
          onResolve={(qc) => {
            captured = qc
          }}
        />
      </ChatProvider>
    )
    await waitFor(() => expect(captured).toBeDefined())
    expect(captured).toBe(external)
    expect(captured!.getDefaultOptions().queries?.staleTime).toBe(7_777)
  })
})
