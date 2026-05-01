import { Component, createContext, type ReactNode, useContext, useEffect } from 'react'
import {
  ChatAuthError,
  ChatHttpError,
  SocketTransportError,
  ThreadConflictError,
  ThreadNotFoundError,
} from '../errors'

export type ChatErrorKey =
  | 'notFound'
  | 'forbidden'
  | 'unauthenticated'
  | 'conflict'
  | 'transport'
  | 'http'
  | 'unknown'

export type ChatErrorFallbackContext = {
  error: Error
  key: ChatErrorKey
  reset: () => void
}

export type ChatErrorFallback = ReactNode | ((ctx: ChatErrorFallbackContext) => ReactNode)

export type ChatErrorBoundaryProps = {
  children: ReactNode
  fallbacks?: Partial<Record<ChatErrorKey, ChatErrorFallback>>
  fallback?: ChatErrorFallback
  onError?: (error: Error, key: ChatErrorKey) => void
  onReset?: () => void
  resetKeys?: unknown[]
}

type State = {
  error: Error | null
}

type ReporterCtx = {
  report: (error: Error) => void
  clear: () => void
}

const ChatErrorBoundaryContext = createContext<ReporterCtx | null>(null)

export function classifyChatError(error: Error): ChatErrorKey {
  if (error instanceof SocketTransportError) {
    if (error.code === 'not_found') return 'notFound'
    if (error.code === 'forbidden') return 'forbidden'
    if (error.code === 'unauthenticated') return 'unauthenticated'
    return 'transport'
  }
  if (error instanceof ThreadNotFoundError) return 'notFound'
  if (error instanceof ChatAuthError) return error.status === 401 ? 'unauthenticated' : 'forbidden'
  if (error instanceof ThreadConflictError) return 'conflict'
  if (error instanceof ChatHttpError) {
    if (error.status === 404) return 'notFound'
    if (error.status === 401) return 'unauthenticated'
    if (error.status === 403) return 'forbidden'
    if (error.status === 409) return 'conflict'
    return 'http'
  }
  return 'unknown'
}

function shallowResetKeysChanged(
  prev: unknown[] | undefined,
  next: unknown[] | undefined
): boolean {
  if (prev === next) return false
  if (!prev || !next) return true
  if (prev.length !== next.length) return true
  for (let i = 0; i < prev.length; i++) {
    if (prev[i] !== next[i]) return true
  }
  return false
}

export class ChatErrorBoundary extends Component<ChatErrorBoundaryProps, State> {
  state: State = { error: null }
  private reporter: ReporterCtx

  constructor(props: ChatErrorBoundaryProps) {
    super(props)
    this.reporter = {
      report: (error: Error) => {
        if (!this.state.error || this.state.error !== error) {
          this.setState({ error })
        }
      },
      clear: () => {
        if (this.state.error) this.setState({ error: null })
      },
    }
  }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error): void {
    if (this.props.onError) {
      this.props.onError(error, classifyChatError(error))
    }
  }

  componentDidUpdate(prevProps: ChatErrorBoundaryProps, prevState: State): void {
    if (this.state.error && prevState.error !== this.state.error && this.props.onError) {
      this.props.onError(this.state.error, classifyChatError(this.state.error))
    }
    if (this.state.error && shallowResetKeysChanged(prevProps.resetKeys, this.props.resetKeys)) {
      this.reset()
    }
  }

  reset = (): void => {
    this.setState({ error: null })
    if (this.props.onReset) this.props.onReset()
  }

  render(): ReactNode {
    const { error } = this.state
    if (error) {
      const key = classifyChatError(error)
      const candidate = this.props.fallbacks?.[key] ?? this.props.fallback
      if (typeof candidate === 'function') {
        return candidate({ error, key, reset: this.reset })
      }
      return candidate ?? null
    }
    return (
      <ChatErrorBoundaryContext.Provider value={this.reporter}>
        {this.props.children}
      </ChatErrorBoundaryContext.Provider>
    )
  }
}

export function useChatErrorReport(error: Error | null | undefined): void {
  const ctx = useContext(ChatErrorBoundaryContext)
  useEffect(() => {
    if (!ctx) return
    if (error) {
      ctx.report(error)
    } else {
      ctx.clear()
    }
  }, [ctx, error])
}
