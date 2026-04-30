import { useStore } from 'zustand'
import type { ConnectionStatus } from '../store/chatStore'
import { useChatStore } from './useChatClient'

export function useChatStatus(): ConnectionStatus {
  const store = useChatStore()
  return useStore(store, (state) => state.connectionStatus)
}
