import { ChatProvider } from '@rfnry/chat-client-react'
import { Chat } from './chat'
import { ROLES, useWorkspace } from './use-workspace'

export function App() {
  const { active, all, select, role, setRole, organization } = useWorkspace()

  const identity = {
    role: 'user' as const,
    id: 'u_alice',
    name: 'Alice',
    metadata: {
      role,
      tenant: { organization, workspace: active.id },
    },
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-3 text-xs">
        <div className="flex gap-2 items-center">
          <span className="text-neutral-500 uppercase tracking-wider">org</span>
          <code className="bg-neutral-900 px-2 py-0.5">{organization}</code>
        </div>
        <div className="flex gap-2">
          {all.map((w) => (
            <button
              key={w.id}
              type="button"
              onClick={() => select(w.id)}
              className={`flex-1 px-3 py-2 text-xs flex flex-col items-start border ${
                w.id === active.id
                  ? 'border-neutral-200 bg-neutral-200 text-black'
                  : 'border-neutral-700 text-neutral-300 hover:border-neutral-500'
              }`}
            >
              <span>{w.label}</span>
              <span
                className={`text-[10px] ${
                  w.id === active.id ? 'text-neutral-600' : 'text-neutral-500'
                }`}
              >
                {w.url}
              </span>
            </button>
          ))}
        </div>
        <div className="flex gap-2 items-center">
          <span className="text-neutral-500 uppercase tracking-wider">role</span>
          {ROLES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRole(r)}
              className={`px-2 py-1 border text-xs ${
                r === role
                  ? 'border-neutral-200 bg-neutral-200 text-black'
                  : 'border-neutral-700 text-neutral-300 hover:border-neutral-500'
              }`}
            >
              {r}
            </button>
          ))}
          {active.id === 'medical' && role === 'member' && (
            <span className="text-amber-400 text-[11px]">
              medical workspace gates AI access to managers
            </span>
          )}
        </div>
      </header>
      {/*
        key={`${active.id}:${role}`} forces React to unmount the old
        ChatProvider and mount a fresh one pointed at the new URL with
        the new identity metadata.
      */}
      <ChatProvider
        key={`${active.id}:${role}`}
        url={active.url}
        identity={identity}
        fallback={
          <p className="text-neutral-500 text-xs">
            Connecting to {active.label} as {role}…
          </p>
        }
        errorFallback={
          <p className="text-red-400 text-xs">
            Unable to reach {active.label} at <code>{active.url}</code>.
          </p>
        }
      >
        <Chat workspace={active} />
      </ChatProvider>
    </div>
  )
}
