import type { Event } from '@rfnry/chat-client-react'
import { useChat } from './use-chat'

export function Chat() {
  const { threadId, status, error, events, isWorking, text, setText, submit } = useChat()

  if (!threadId) return <p>Setting up thread…</p>
  if (status === 'joining') return <p>Joining…</p>
  if (status === 'error') return <p>Error: {error?.message}</p>

  return (
    <>
      <EventFeed events={events} />
      {isWorking && (
        <div style={{ color: '#888', margin: '8px 0' }}>Assistant is working…</div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit()
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
