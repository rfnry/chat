import { buttonCls, EventFeed, inputCls } from '../../ui'
import { useChat } from './use-chat'

export function Chat() {
  const { threadId, status, error, events, isWorking, text, setText, submit } = useChat()

  if (!threadId) return <p className="text-neutral-500 text-xs">Setting up thread…</p>
  if (status === 'joining') return <p className="text-neutral-500 text-xs">Joining…</p>
  if (status === 'error') return <p className="text-red-400 text-xs">Error: {error?.message}</p>

  return (
    <section className="flex flex-col gap-3">
      <header className="text-xs text-neutral-500">
        chat with the cs-agent. send a message, the agent forwards it to Anthropic and replies.
      </header>
      <EventFeed events={events} />
      {isWorking && <div className="text-neutral-500 text-xs">assistant is working…</div>}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
        className="flex gap-2"
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Say hi…"
          className={inputCls}
        />
        <button type="submit" className={buttonCls}>
          send
        </button>
      </form>
    </section>
  )
}
