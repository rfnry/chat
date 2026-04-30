export class ChatHttpError extends Error {
  constructor(
    readonly status: number,
    readonly body: string
  ) {
    super(`HTTP ${status}: ${body}`)
    this.name = 'ChatHttpError'
  }
}

export class ThreadNotFoundError extends ChatHttpError {
  constructor(body: string) {
    super(404, body)
    this.name = 'ThreadNotFoundError'
  }
}

export class ChatAuthError extends ChatHttpError {
  constructor(status: 401 | 403, body: string) {
    super(status, body)
    this.name = 'ChatAuthError'
  }
}

export class ThreadConflictError extends ChatHttpError {
  constructor(body: string) {
    super(409, body)
    this.name = 'ThreadConflictError'
  }
}

export function httpErrorFor(status: number, body: string): ChatHttpError {
  if (status === 404) return new ThreadNotFoundError(body)
  if (status === 401 || status === 403) return new ChatAuthError(status, body)
  if (status === 409) return new ThreadConflictError(body)
  return new ChatHttpError(status, body)
}

export class SocketTransportError extends Error {
  readonly code: string
  constructor(code: string, message: string) {
    super(`${code}: ${message}`)
    this.name = 'SocketTransportError'
    this.code = code
  }
}
