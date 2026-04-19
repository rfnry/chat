import { useSyncExternalStore } from 'react'
import { useChatStore } from './useChatClient'

export function useConnectionStatus() {
  const store = useChatStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => store.getState().connectionStatus,
    () => store.getState().connectionStatus
  )
}
