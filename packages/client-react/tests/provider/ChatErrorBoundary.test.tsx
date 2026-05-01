import { act, render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  ChatAuthError,
  ChatHttpError,
  SocketTransportError,
  ThreadConflictError,
  ThreadNotFoundError,
} from '../../src/errors'
import {
  ChatErrorBoundary,
  classifyChatError,
  useChatErrorReport,
} from '../../src/provider/ChatErrorBoundary'

function Reporter({ error }: { error: Error | null }) {
  useChatErrorReport(error)
  return <span data-testid="ok">ok</span>
}

function Thrower({ error }: { error: Error | null }) {
  if (error) throw error
  return <span data-testid="ok">ok</span>
}

describe('classifyChatError', () => {
  it('classifies SocketTransportError by code', () => {
    expect(classifyChatError(new SocketTransportError('not_found', 'x'))).toBe('notFound')
    expect(classifyChatError(new SocketTransportError('forbidden', 'x'))).toBe('forbidden')
    expect(classifyChatError(new SocketTransportError('unauthenticated', 'x'))).toBe(
      'unauthenticated'
    )
    expect(classifyChatError(new SocketTransportError('weird', 'x'))).toBe('transport')
  })

  it('classifies ChatHttpError subclasses', () => {
    expect(classifyChatError(new ThreadNotFoundError('x'))).toBe('notFound')
    expect(classifyChatError(new ThreadConflictError('x'))).toBe('conflict')
    expect(classifyChatError(new ChatAuthError(401, 'x'))).toBe('unauthenticated')
    expect(classifyChatError(new ChatAuthError(403, 'x'))).toBe('forbidden')
    expect(classifyChatError(new ChatHttpError(500, 'x'))).toBe('http')
  })

  it('classifies unknown errors', () => {
    expect(classifyChatError(new Error('boom'))).toBe('unknown')
  })
})

describe('ChatErrorBoundary', () => {
  it('renders children when no error is reported', () => {
    const { getByTestId } = render(
      <ChatErrorBoundary fallback={<span data-testid="fb">fb</span>}>
        <Reporter error={null} />
      </ChatErrorBoundary>
    )
    expect(getByTestId('ok')).toBeDefined()
  })

  it('swaps to the matching fallback when a hook reports a typed error', async () => {
    const { getByTestId } = render(
      <ChatErrorBoundary
        fallbacks={{ notFound: <span data-testid="not-found">not-found</span> }}
        fallback={<span data-testid="default">default</span>}
      >
        <Reporter error={new ThreadNotFoundError('th_1 missing')} />
      </ChatErrorBoundary>
    )
    await waitFor(() => expect(getByTestId('not-found')).toBeDefined())
  })

  it('uses the default fallback when no specific match is registered', async () => {
    const { getByTestId } = render(
      <ChatErrorBoundary fallback={<span data-testid="fb">fb</span>}>
        <Reporter error={new ChatHttpError(500, 'boom')} />
      </ChatErrorBoundary>
    )
    await waitFor(() => expect(getByTestId('fb')).toBeDefined())
  })

  it('passes error + key + reset to function fallbacks', async () => {
    const { getByTestId } = render(
      <ChatErrorBoundary
        fallbacks={{
          forbidden: ({ error: e, key }) => (
            <span data-testid="fb" data-key={key}>
              {e.message}
            </span>
          ),
        }}
      >
        <Reporter error={new SocketTransportError('forbidden', 'no perms')} />
      </ChatErrorBoundary>
    )
    await waitFor(() => expect(getByTestId('fb')).toBeDefined())
    expect(getByTestId('fb').dataset.key).toBe('forbidden')
  })

  it('reset() clears the error and re-renders children', async () => {
    let triggerReset: (() => void) | undefined

    function Page({ reportedError }: { reportedError: Error | null }) {
      return (
        <ChatErrorBoundary
          fallbacks={{
            notFound: ({ reset }) => {
              triggerReset = reset
              return <span data-testid="fb">fb</span>
            },
          }}
        >
          <Reporter error={reportedError} />
        </ChatErrorBoundary>
      )
    }

    const { getByTestId, rerender } = render(
      <Page reportedError={new ThreadNotFoundError('gone')} />
    )
    await waitFor(() => expect(getByTestId('fb')).toBeDefined())

    rerender(<Page reportedError={null} />)
    act(() => {
      triggerReset?.()
    })
    await waitFor(() => expect(getByTestId('ok')).toBeDefined())
  })

  it('catches synchronous render-time throws via getDerivedStateFromError', () => {
    const onError = vi.fn()
    // Suppress React's expected console.error from the thrown render
    const restore = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { getByTestId } = render(
      <ChatErrorBoundary fallback={<span data-testid="fb">fb</span>} onError={onError}>
        <Thrower error={new SocketTransportError('forbidden', 'sync')} />
      </ChatErrorBoundary>
    )
    expect(getByTestId('fb')).toBeDefined()
    expect(onError).toHaveBeenCalled()
    const [, key] = onError.mock.calls[0] ?? []
    expect(key).toBe('forbidden')
    restore.mockRestore()
  })

  it('without a boundary, useChatErrorReport is a no-op', () => {
    const { getByTestId } = render(<Reporter error={new ThreadNotFoundError('x')} />)
    expect(getByTestId('ok')).toBeDefined()
  })

  it('onError fires with the classified key when an error is reported', async () => {
    const onError = vi.fn()
    render(
      <ChatErrorBoundary onError={onError} fallback={<span data-testid="fb">fb</span>}>
        <Reporter error={new ChatAuthError(401, 'sign in')} />
      </ChatErrorBoundary>
    )
    await waitFor(() => expect(onError).toHaveBeenCalled())
    const [, key] = onError.mock.calls[0] ?? []
    expect(key).toBe('unauthenticated')
  })
})
