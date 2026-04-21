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

const THREAD_KEY = 'rfnry-demo-customer-support-thread-id'
const AGENT_ID = 'cs-agent'

const USER = { role: 'user' as const, id: 'u_alice', name: 'Alice', metadata: {} }
const AGENT = {
  role: 'assistant' as const,
  id: AGENT_ID,
  name: 'Customer Support',
  metadata: {},
}

export type UseChat = {
  threadId: string | null
  status: SessionStatus
  error?: Error
  events: Event[]
  isWorking: boolean
  text: string
  setText: (text: string) => void
  submit: () => void
}

export function useChat(): UseChat {
  const threadId = useDemoThread()
  const session = useThreadSession(threadId)
  const events = useThreadEvents(threadId)
  const isWorking = useThreadIsWorking(threadId)
  const { send } = useThreadActions(threadId)
  const [text, setText] = useState('')

  const submit = useCallback(() => {
    if (!threadId) return
    const trimmed = text.trim()
    if (!trimmed) return
    void send({
      clientId: crypto.randomUUID(),
      content: [{ type: 'text', text: trimmed }],
      recipients: [AGENT_ID],
    })
    setText('')
  }, [send, text, threadId])

  return {
    threadId,
    status: session.status,
    error: session.error,
    events,
    isWorking,
    text,
    setText,
    submit,
  }
}

function useDemoThread(): string | null {
  const [threadId, setThreadId] = useState<string | null>(() =>
    localStorage.getItem(THREAD_KEY),
  )
  const { mutateAsync: createThread } = useCreateThread()
  const client = useChatClient()

  useEffect(() => {
    if (threadId) return
    let cancelled = false
    void (async () => {
      const thread = await createThread({ tenant: {} })
      await client.addMember(thread.id, USER)
      await client.addMember(thread.id, AGENT)
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
