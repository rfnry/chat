import type { Event } from '@rfnry/chat-protocol'
import { createContext } from 'react'
import type { ChatClient } from '../client'
import type { ChatStore } from '../store/chatStore'
import type { PresenceSlice } from '../store/presence'

export type EventListener = (event: Event) => void

export type EventRegistry = {
  subscribe(listener: EventListener): () => void
}

export type ChatContextValue = {
  client: ChatClient
  store: ChatStore
  events: EventRegistry
  presence: PresenceSlice
}

export const ChatContext = createContext<ChatContextValue | null>(null)
ChatContext.displayName = 'ChatContext'
