import {
  type Event,
  type SessionStatus,
  useChatClient,
  useCreateThread,
  useThreadActions,
  useThreadEvents,
  useThreadIsWorking,
  useThreadSession,
} from '@rfnry/chat-client-react'
import { useCallback, useEffect, useState } from 'react'

const THREAD_KEY = 'rfnry-demo-stock-tool-thread-id'
const DEFAULT_SKU = 'FBA-MERV11-16x25x1'

const USER = {
  role: 'user' as const,
  id: 'u_alice',
  name: 'Alice',
  metadata: {},
}

export type UseChat = {
  threadId: string | null
  status: SessionStatus
  error?: Error
  events: Event[]
  isWorking: boolean
  sku: string
  setSku: (sku: string) => void
  askStock: () => void
}

export function useChat(): UseChat {
  const threadId = useDemoThread()
  const session = useThreadSession(threadId)
  const events = useThreadEvents(threadId)
  const isWorking = useThreadIsWorking(threadId)
  const { emit } = useThreadActions(threadId)
  const [sku, setSku] = useState(DEFAULT_SKU)

  const askStock = useCallback(() => {
    if (!threadId) return
    void emit({
      type: 'tool.call',
      tool: {
        id: `call_${crypto.randomUUID()}`,
        name: 'check_stock',
        arguments: { sku },
      },
    })
  }, [emit, sku, threadId])

  return {
    threadId,
    status: session.status,
    error: session.error,
    events,
    isWorking,
    sku,
    setSku,
    askStock,
  }
}

// On first mount, creates a thread and adds the user as a member. Persists
// the id in localStorage so a page refresh reuses the same thread.
function useDemoThread(): string | null {
  const [threadId, setThreadId] = useState<string | null>(() =>
    localStorage.getItem(THREAD_KEY)
  )
  const { mutateAsync: createThread } = useCreateThread()
  const client = useChatClient()

  useEffect(() => {
    if (threadId) return
    let cancelled = false
    void (async () => {
      const thread = await createThread({ tenant: {} })
      await client.addMember(thread.id, USER)
      if (cancelled) return
      localStorage.setItem(THREAD_KEY, thread.id)
      setThreadId(thread.id)
    })()
    return () => {
      cancelled = true
    }
  }, [client, createThread, threadId])

  return threadId
}
