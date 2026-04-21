import { ChatProvider } from '@rfnry/chat-client-react'
import { Inbox } from './inbox'
import { Layout } from './layout'

const USER_ID = 'u_alice'

export function App() {
  return (
    <ChatProvider
      url="http://localhost:8000"
      authenticate={async () => ({
        headers: { authorization: `Bearer ${USER_ID}` },
      })}
      onThreadInvited={(thread, addedBy) => {
        console.log('[invited]', thread.id, 'by', addedBy.id)
      }}
      fallback={
        <Layout>
          <p>Connecting…</p>
        </Layout>
      }
      errorFallback={
        <Layout>
          <p>Unable to reach the chat server.</p>
        </Layout>
      }
    >
      <Layout>
        <Inbox />
      </Layout>
    </ChatProvider>
  )
}
