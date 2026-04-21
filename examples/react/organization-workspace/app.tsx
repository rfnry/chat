import { ChatProvider } from '@rfnry/chat-client-react'
import { Chat } from './chat'
import { Layout } from './layout'
import { useWorkspace } from './use-workspace'

export function App() {
  const { active, all, select } = useWorkspace()

  return (
    <Layout workspaces={all} activeId={active.id} onSelect={select}>
      {/*
        key={active.id} forces React to unmount the old ChatProvider (which
        triggers its cleanup → client.disconnect()) and mount a fresh one
        pointed at the new workspace URL. This is how one React app switches
        its ChatClient between independent chat-server deployments.
      */}
      <ChatProvider
        key={active.id}
        url={active.url}
        authenticate={async () => ({ headers: { authorization: 'Bearer u_alice' } })}
        fallback={<p>Connecting to {active.label}…</p>}
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
