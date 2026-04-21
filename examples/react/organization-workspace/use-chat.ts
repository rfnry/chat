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
import type { Workspace } from './workspaces'

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
  text: string
  setText: (text: string) => void
  submit: () => void
}

export function useChat(workspace: Workspace): UseChat {
  const threadId = useDemoThread(workspace)
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
      recipients: [workspace.agentId],
    })
    setText('')
  }, [send, text, threadId, workspace])

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

// Per-workspace thread: the id is stored in a workspace-scoped localStorage
// key, so switching to another workspace starts a fresh thread there and
// switching back reuses the original.
function useDemoThread(workspace: Workspace): string | null {
  const storageKey = `rfnry-demo-org-${workspace.id}-thread-id`
  const [threadId, setThreadId] = useState<string | null>(() =>
    localStorage.getItem(storageKey)
  )
  const { mutateAsync: createThread } = useCreateThread()
  const client = useChatClient()

  useEffect(() => {
    setThreadId(localStorage.getItem(storageKey))
  }, [storageKey])

  useEffect(() => {
    if (threadId) return
    let cancelled = false
    void (async () => {
      const thread = await createThread({ tenant: { workspace: workspace.id } })
      await client.addMember(thread.id, USER)
      await client.addMember(thread.id, {
        role: 'assistant' as const,
        id: workspace.agentId,
        name: workspace.agentName,
        metadata: { workspace: workspace.id },
      })
      if (cancelled) return
      localStorage.setItem(storageKey, thread.id)
      setThreadId(thread.id)
    })()
    return () => {
      cancelled = true
    }
  }, [client, createThread, threadId, storageKey, workspace])

  return threadId
}
