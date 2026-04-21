import {
  ChatProvider,
  type Event,
  useThreadActions,
  useThreadEvents,
  useThreadIsWorking,
  useThreadSession,
} from '@rfnry/chat-client-react'
import { useState } from 'react'

// Entry. One ChatProvider wraps both demos; they share the socket + REST +
// store. Point `url` at whichever backend example you're running
// (examples/server-python/customer-support or examples/server-python/stock-tool).
export function App() {
  const [demo, setDemo] = useState<'customer-support' | 'stock-tool'>('customer-support')
  return (
    <ChatProvider
      url="http://localhost:8000"
      authenticate={async () => ({
        headers: { authorization: 'Bearer u_alice' },
      })}
      fallback={<div>Connecting…</div>}
      errorFallback={<div>Unable to connect to the chat server.</div>}
    >
      <div style={{ padding: 24, fontFamily: 'system-ui' }}>
        <nav style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <button type="button" onClick={() => setDemo('customer-support')}>
            customer-support
          </button>
          <button type="button" onClick={() => setDemo('stock-tool')}>
            stock-tool
          </button>
        </nav>
        {demo === 'customer-support' ? (
          <CustomerSupport threadId="th_demo_cs" />
        ) : (
          <StockTool threadId="th_demo_stock" />
        )}
      </div>
    </ChatProvider>
  )
}

// ---------------------------------------------------------------------------
// customer-support: user posts messages; the backend agent (rfnry-chat-client
// running alongside the chat server) replies inside a Run. The UI sends text
// with recipients=['cs-agent'] so the message is addressed; the agent's
// default recipient filter picks it up. The "working…" indicator comes from
// useThreadIsWorking, which tracks active Runs in the store.
// ---------------------------------------------------------------------------
function CustomerSupport({ threadId }: { threadId: string }) {
  const session = useThreadSession(threadId)
  const events = useThreadEvents(threadId)
  const isWorking = useThreadIsWorking(threadId)
  const { send } = useThreadActions(threadId)
  const [text, setText] = useState('')

  if (session.status === 'joining') return <div>Joining thread…</div>
  if (session.status === 'error') return <div>Error: {session.error?.message}</div>

  return (
    <section>
      <h2>customer-support</h2>
      <EventList events={events} />
      {isWorking && <div style={{ color: '#888' }}>Assistant is working…</div>}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!text.trim()) return
          void send({
            clientId: crypto.randomUUID(),
            content: [{ type: 'text', text }],
            recipients: ['cs-agent'],
          })
          setText('')
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask about an order…"
          style={{ width: 320 }}
        />
        <button type="submit">Send</button>
      </form>
    </section>
  )
}

// ---------------------------------------------------------------------------
// stock-tool: no agent. The user triggers a tool.call event via `emit()`; a
// server-side @server.on_tool_call handler answers with tool.result. The UI
// renders tool.call + tool.result inline through the same event feed,
// demonstrating that humans and server-side handlers use the same protocol.
// ---------------------------------------------------------------------------
function StockTool({ threadId }: { threadId: string }) {
  const session = useThreadSession(threadId)
  const events = useThreadEvents(threadId)
  const { emit } = useThreadActions(threadId)
  const [sku, setSku] = useState('FBA-MERV11-16x25x1')

  if (session.status === 'joining') return <div>Joining thread…</div>
  if (session.status === 'error') return <div>Error: {session.error?.message}</div>

  const askStock = () => {
    // The server's event:send handler fills in id, author, thread_id and
    // created_at from the socket session, so we only need the event-specific
    // fields here.
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
    <section>
      <h2>stock-tool</h2>
      <EventList events={events} />
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={sku}
          onChange={(e) => setSku(e.target.value)}
          placeholder="SKU"
          style={{ width: 240 }}
        />
        <button type="button" onClick={askStock}>
          check_stock
        </button>
      </div>
    </section>
  )
}

// Shared event renderer. Works for both demos because every interaction
// flows through the same event protocol.
function EventList({ events }: { events: Event[] }) {
  return (
    <ul>
      {events.map((e) => (
        <li key={e.id}>{renderEvent(e)}</li>
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
      return `${e.author.name} → tool ${e.tool.name}(${JSON.stringify(e.tool.arguments)})`
    case 'tool.result':
      return `tool ${e.tool.id} → ${
        e.tool.error ? `error: ${e.tool.error.code}` : JSON.stringify(e.tool.result)
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
