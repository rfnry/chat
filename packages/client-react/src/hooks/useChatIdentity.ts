import type { Identity } from '@rfnry/chat-protocol'
import { useContext } from 'react'
import { ChatContext } from '../provider/ChatContext'

export function useChatIdentity(): Identity | null {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useChatIdentity must be used inside <ChatProvider>')
  return ctx.client.identity
}
