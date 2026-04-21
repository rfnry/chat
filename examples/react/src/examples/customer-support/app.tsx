import { ChatProvider } from '@rfnry/chat-client-react'
import { Chat } from './chat'

const IDENTITY = { role: 'user' as const, id: 'u_alice', name: 'Alice', metadata: {} }

export function App() {
  return (
    <ChatProvider
      url="http://localhost:8000"
      identity={IDENTITY}
      fallback={<p className="text-neutral-500 text-xs">Connecting…</p>}
      errorFallback={
        <p className="text-red-400 text-xs">
          Unable to reach the customer-support backend at localhost:8000.
        </p>
      }
    >
      <Chat />
    </ChatProvider>
  )
}
