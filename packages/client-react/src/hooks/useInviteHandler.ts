import { type ThreadInvitedFrame, toThreadInvitedFrame } from '@rfnry/chat-protocol'
import { useEffect, useRef } from 'react'
import { useChatClient } from './useChatClient'

export type InviteHandler = (frame: ThreadInvitedFrame) => void | Promise<void>

/**
 * Subscribe to `thread:invited` frames with the full parsed frame.
 *
 * Mirrors Python's `@on_invited` — hands over `ThreadInvitedFrame(thread,
 * addedMember, addedBy)` rather than the lossy `(thread, addedBy)` tuple
 * exposed by `ChatProvider`'s `onThreadInvited` prop. Use this hook when the
 * UI needs to know *who* was added (e.g. group-chat invites where the
 * invitee may not be the connected identity).
 *
 * Auto-join behaviour lives on `ChatProvider` (prop `autoJoinOnInvite`,
 * default `true`). If you opt out there, call `client.joinThread(...)` from
 * within this handler to take over the decision.
 */
export function useInviteHandler(handler: InviteHandler): void {
  const client = useChatClient()
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  useEffect(() => {
    const off = client.on('thread:invited', (raw: unknown) => {
      const frame = toThreadInvitedFrame(raw as never)
      void handlerRef.current(frame)
    })
    return off
  }, [client])
}
