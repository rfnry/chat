import { createContext } from 'react'
import type { ChatClient } from '../client/ChatClient'
import type { ChatStore } from '../store/chatStore'

export type ChatContextValue = {
  client: ChatClient
  store: ChatStore
}

export const ChatContext = createContext<ChatContextValue | null>(null)
ChatContext.displayName = 'ChatContext'
