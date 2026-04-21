import {
  type Event,
  useChatClient,
  useCreateThread,
  useThreadActions,
  useThreadEvents,
  useThreadIsWorking,
  useThreadSession,
} from '@rfnry/chat-client-react'
import { useEffect, useState } from 'react'

const THREAD_KEY = 'rfnry-demo-customer-support-thread-id'
const AGENT_ID = 'cs-agent'

const USER = {
  role: 'user' as const,
  id: 'u_alice',
  name: 'Alice',
  metadata: {},
}

const AGENT = {
  role: 'assistant' as const,
  id: AGENT_ID,
  name: 'Customer Support',
  metadata: {},
}

export function Chat() {
  const threadId = useDemoThread()
  if (!threadId) return <p>Setting up thread…</p>
  return <Thread threadId={threadId} />
}

// On first mount, creates a thread and adds both the user and the agent as
// members. The agent identity must match the one the Python agent service
// authenticates as (src/settings.py → ASSISTANT_ID).
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

function Thread({ threadId }: { threadId: string }) {
  const session = useThreadSession(threadId)
  const events = useThreadEvents(threadId)
  const isWorking = useThreadIsWorking(threadId)
  const { send } = useThreadActions(threadId)
  const [text, setText] = useState('')

  if (session.status === 'joining') return <p>Joining…</p>
  if (session.status === 'error') return <p>Error: {session.error?.message}</p>

  return (
    <>
      <EventFeed events={events} />
      {isWorking && (
        <div style={{ color: '#888', margin: '8px 0' }}>Assistant is working…</div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!text.trim()) return
          void send({
            clientId: crypto.randomUUID(),
            content: [{ type: 'text', text }],
            recipients: [AGENT_ID],
          })
          setText('')
        }}
        style={{ display: 'flex', gap: 8, marginTop: 12 }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask about an order (e.g. ORD-1001)…"
          style={{ flex: 1, padding: '6px 8px' }}
        />
        <button type="submit">Send</button>
      </form>
    </>
  )
}

function EventFeed({ events }: { events: Event[] }) {
  return (
    <ul style={{ padding: 0, margin: 0, listStyle: 'none' }}>
      {events.map((e) => (
        <li
          key={e.id}
          style={{ padding: '4px 0', borderBottom: '1px dashed #eee', fontSize: 13 }}
        >
          {renderEvent(e)}
        </li>
      ))}
    </ul>
  )
}

function renderEvent(e: Event): string {
  switch (e.type) {
    case 'message': {
      const text = e.content.find((p) => p.type === 'text')
      return `${e.author.name}: ${text && text.type === 'text' ? text.text : '[media]'}`
    }
    case 'reasoning':
      return `${e.author.name} (reasoning): ${e.content}`
    case 'tool.call':
      return `${e.author.name} → ${e.tool.name}(${JSON.stringify(e.tool.arguments)})`
    case 'tool.result':
      return `← ${e.tool.id}: ${
        e.tool.error ? `error ${e.tool.error.code}` : JSON.stringify(e.tool.result)
      }`
    case 'run.started':
      return '— run started —'
    case 'run.completed':
      return '— run completed —'
    case 'run.failed':
      return `— run failed: ${e.error.message} —`
    case 'run.cancelled':
      return '— run cancelled —'
    case 'thread.member_added':
      return `+ ${e.member.name} joined`
    case 'thread.member_removed':
      return `- ${e.member.name} left`
    default:
      return `[${e.type}]`
  }
}
