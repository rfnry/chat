import type { Identity } from '@rfnry/chat-protocol'
import { useContext } from 'react'
import { ChatContext } from '../provider/ChatContext'

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

export function useIdentity(): Identity | null {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useIdentity must be used inside <ChatProvider>')
  return ctx.client.identity
}
