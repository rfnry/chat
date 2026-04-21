import { useThreadEvents, useThreads } from '@rfnry/chat-client-react'

export function Inbox() {
  const { data, isLoading } = useThreads({ limit: 50 })
  if (isLoading) return <p>Loading…</p>
  const threads = data?.items ?? []
  if (threads.length === 0) {
    return (
      <p style={{ color: '#666' }}>
        No threads yet. Trigger the agent webhook to start a conversation.
      </p>
    )
  }
  return (
    <ul style={{ padding: 0, margin: 0, listStyle: 'none' }}>
      {threads.map((t) => (
        <ThreadRow key={t.id} threadId={t.id} />
      ))}
    </ul>
  )
}

function ThreadRow({ threadId }: { threadId: string }) {
  const events = useThreadEvents(threadId)
  const lastMessage = [...events].reverse().find((e) => e.type === 'message')
  const text =
    lastMessage && 'content' in lastMessage
      ? lastMessage.content
          .filter((p): p is { type: 'text'; text: string } => p.type === 'text')
          .map((p) => p.text)
          .join(' ')
      : '(no messages yet)'
  return (
    <li style={{ padding: '8px 0', borderBottom: '1px solid #eee' }}>
      <strong style={{ fontFamily: 'monospace' }}>{threadId}</strong>
      <div style={{ color: '#444', marginTop: 2 }}>{text}</div>
    </li>
  )
}
