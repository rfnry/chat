import type {
  Identity,
  PresenceJoinedFrame,
  PresenceLeftFrame,
  PresenceSnapshot,
} from '@rfnry/chat-protocol'
import { createStore, type StoreApi } from 'zustand/vanilla'

export type PresenceSliceState = {
  members: Map<string, Identity>
  hydrated: boolean
}

// Hybrid shape: spreads StoreApi (exposes getState/setState/subscribe for
// useStore-based reactivity in useChatPresence) AND exposes flat ergonomic methods
// so ChatProvider can call `presence.hydrate(snapshot)` directly. This diverges
// from chatStore.ts (which nests actions under state.actions) — presence chose
// the flatter surface because its actions are called from non-React code
// (socket handlers in the provider), where the nested form would force a
// getState() + method-lookup dance at every call site.
export type PresenceSlice = StoreApi<PresenceSliceState> & {
  hydrate(snapshot: PresenceSnapshot): void
  applyJoined(frame: PresenceJoinedFrame): void
  applyLeft(frame: PresenceLeftFrame): void
  list(): Identity[]
  isHydrated(): boolean
}

export type PresenceStore = ReturnType<typeof createPresenceSlice>

const initialState = (): PresenceSliceState => ({
  members: new Map(),
  hydrated: false,
})

export function createPresenceSlice(): PresenceSlice {
  const store = createStore<PresenceSliceState>(() => initialState())

  return {
    ...store,
    hydrate(snapshot) {
      const next = new Map<string, Identity>()
      for (const identity of snapshot.members) next.set(identity.id, identity)
      store.setState({ members: next, hydrated: true }, true)
    },
    applyJoined(frame) {
      store.setState((state) => {
        if (state.members.has(frame.identity.id)) return state
        const next = new Map(state.members)
        next.set(frame.identity.id, frame.identity)
        return { ...state, members: next }
      })
    },
    applyLeft(frame) {
      store.setState((state) => {
        if (!state.members.has(frame.identity.id)) return state
        const next = new Map(state.members)
        next.delete(frame.identity.id)
        return { ...state, members: next }
      })
    },
    list() {
      return Array.from(store.getState().members.values())
    },
    isHydrated() {
      return store.getState().hydrated
    },
  }
}
