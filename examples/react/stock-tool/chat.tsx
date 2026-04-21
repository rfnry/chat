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

const THREAD_KEY = 'rfnry-demo-stock-tool-thread-id'

const USER = {
  role: 'user' as const,
  id: 'u_alice',
  name: 'Alice',
  metadata: {},
}

export function Chat() {
  const threadId = useDemoThread()
  if (!threadId) return <p>Setting up thread…</p>
  return <Thread threadId={threadId} />
}

// On first mount, creates a thread and adds the user as a member. Persists
// the thread id in localStorage so a page refresh reuses the same thread.
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

function Thread({ threadId }: { threadId: string }) {
  const session = useThreadSession(threadId)
  const events = useThreadEvents(threadId)
  const isWorking = useThreadIsWorking(threadId)
  const { emit } = useThreadActions(threadId)
  const [sku, setSku] = useState('FBA-MERV11-16x25x1')

  if (session.status === 'joining') return <p>Joining…</p>
  if (session.status === 'error') return <p>Error: {session.error?.message}</p>

  // Server fills in id, author, thread_id, created_at from the socket
  // session — we pass only the event-specific fields.
  const askStock = () => {
    void emit({
      type: 'tool.call',
      tool: {
        id: `call_${crypto.randomUUID()}`,
        name: 'check_stock',
        arguments: { sku },
      },
    })
  }

  return (
    <>
      <EventFeed events={events} />
      {isWorking && <div style={{ color: '#888', margin: '8px 0' }}>Server is working…</div>}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          askStock()
        }}
        style={{ display: 'flex', gap: 8, marginTop: 12 }}
      >
        <input
          value={sku}
          onChange={(e) => setSku(e.target.value)}
          placeholder="SKU"
          style={{ flex: 1, padding: '6px 8px' }}
        />
        <button type="submit">check_stock</button>
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
