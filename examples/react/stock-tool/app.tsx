import { ChatProvider } from '@rfnry/chat-client-react'
import { Chat } from './chat'
import { Layout } from './layout'

export function App() {
  return (
    <ChatProvider
      url="http://localhost:8000"
      authenticate={async () => ({
        headers: { authorization: 'Bearer u_alice' },
      })}
      fallback={<Layout><p>Connecting…</p></Layout>}
      errorFallback={<Layout><p>Unable to reach the chat server.</p></Layout>}
    >
      <Layout>
        <Chat />
      </Layout>
    </ChatProvider>
  )
}
