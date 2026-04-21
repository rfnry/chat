import { ChatProvider } from '@rfnry/chat-client-react'
import { Chat } from './chat'
import { Layout } from './layout'
import { useWorkspace } from './use-workspace'

export function App() {
  const { active, all, select, role, setRole, organization } = useWorkspace()

  return (
    <Layout
      workspaces={all}
      activeId={active.id}
      onSelect={select}
      role={role}
      onRoleChange={setRole}
      organization={organization}
    >
      {/*
        key={`${active.id}:${role}`} forces React to unmount the old
        ChatProvider (client.disconnect() runs in its effect cleanup) and
        mount a fresh one pointed at the new URL / authenticating with the
        new role. This is how one React app reconnects across independent
        chat-server deployments AND re-auths with different tenant data.
      */}
      <ChatProvider
        key={`${active.id}:${role}`}
        url={active.url}
        authenticate={async () => ({
          headers: { authorization: 'Bearer u_alice' },
          auth: { organization, role },
        })}
        fallback={<p>Connecting to {active.label} as {role}…</p>}
        errorFallback={
          <p>
            Unable to reach the {active.label} workspace at <code>{active.url}</code>.
          </p>
        }
      >
        <Chat workspace={active} />
      </ChatProvider>
    </Layout>
  )
}
