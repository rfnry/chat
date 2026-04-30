import type {
  AssistantIdentity,
  Identity,
  SystemIdentity,
  UserIdentity,
} from '@rfnry/chat-protocol'
import { useContext, useMemo } from 'react'
import { useStore } from 'zustand'
import { ChatContext } from '../provider/ChatContext'

export type PresenceByRole = {
  user: UserIdentity[]
  assistant: AssistantIdentity[]
  system: SystemIdentity[]
}

export type ChatPresence = {
  members: Identity[]
  byRole: PresenceByRole
  isHydrated: boolean
}

/**
 * Returns connection-scoped presence — who is currently online in this
 * client's namespace. Mirrors the server's namespace-wide presence
 * broadcast (`presence:joined` / `presence:left` frames carry only an
 * identity, not a thread id).
 *
 * For the canonical roster of a specific thread (database-backed), use
 * {@link useChatMembers}.
 */
export function useChatPresence(): ChatPresence {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useChatPresence must be used inside <ChatProvider>')
  const { presence } = ctx

  const membersMap = useStore(presence, (s) => s.members)
  const isHydrated = useStore(presence, (s) => s.hydrated)

  const members = useMemo(() => Array.from(membersMap.values()), [membersMap])

  const byRole = useMemo<PresenceByRole>(() => {
    const user: UserIdentity[] = []
    const assistant: AssistantIdentity[] = []
    const system: SystemIdentity[] = []
    for (const m of members) {
      if (m.role === 'user') user.push(m)
      else if (m.role === 'assistant') assistant.push(m)
      else if (m.role === 'system') system.push(m)
    }
    return { user, assistant, system }
  }, [members])

  return { members, byRole, isHydrated }
}
