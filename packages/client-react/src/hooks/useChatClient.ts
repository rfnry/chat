import { useContext } from 'react'
import { ChatContext, type EventRegistry } from '../provider/ChatContext'

export function useChatClient() {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useChatClient must be used inside <ChatProvider>')
  return ctx.client
}

export function useChatStore() {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useChatStore must be used inside <ChatProvider>')
  return ctx.store
}

export function useChatEvents(): EventRegistry {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useChatEvents must be used within ChatProvider')
  return ctx.events
}
