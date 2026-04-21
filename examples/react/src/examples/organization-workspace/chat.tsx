import { buttonCls, EventFeed, inputCls } from '../../ui'
import { useChat } from './use-chat'
import type { Workspace } from './use-workspace'

export function Chat({ workspace }: { workspace: Workspace }) {
  const { threadId, status, error, events, isWorking, text, setText, submit } = useChat(workspace)

  if (!threadId)
    return <p className="text-neutral-500 text-xs">Setting up {workspace.label} thread…</p>
  if (status === 'joining') return <p className="text-neutral-500 text-xs">Joining…</p>
  if (status === 'error') return <p className="text-red-400 text-xs">Error: {error?.message}</p>

  return (
    <section className="flex flex-col gap-3">
      <EventFeed events={events} />
      {isWorking && (
        <div className="text-neutral-500 text-xs">{workspace.agentName} is working…</div>
      )}
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
          placeholder={workspace.placeholder}
          className={inputCls}
        />
        <button type="submit" className={buttonCls}>
          send
        </button>
      </form>
    </section>
  )
}
