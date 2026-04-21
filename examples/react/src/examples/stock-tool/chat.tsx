import { buttonCls, EventFeed, inputCls } from '../../ui'
import { useChat } from './use-chat'

export function Chat() {
  const { threadId, status, error, events, isWorking, sku, setSku, askStock } = useChat()

  if (!threadId) return <p className="text-neutral-500 text-xs">Setting up thread…</p>
  if (status === 'joining') return <p className="text-neutral-500 text-xs">Joining…</p>
  if (status === 'error') return <p className="text-red-400 text-xs">Error: {error?.message}</p>

  return (
    <section className="flex flex-col gap-3">
      <header className="text-xs text-neutral-500">
        server-side <code className="text-neutral-300">check_stock</code> tool — no AI
      </header>
      <EventFeed events={events} />
      {isWorking && <div className="text-neutral-500 text-xs">server is working…</div>}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          askStock()
        }}
        className="flex gap-2"
      >
        <input
          value={sku}
          onChange={(e) => setSku(e.target.value)}
          placeholder="SKU"
          className={inputCls}
        />
        <button type="submit" className={buttonCls}>
          check_stock
        </button>
      </form>
    </section>
  )
}
