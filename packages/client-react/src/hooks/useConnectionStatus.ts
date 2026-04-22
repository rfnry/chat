import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

export function useConnectionStatus() {
  const store = useChatStore()
  return useStore(store, (state) => state.connectionStatus)
}
