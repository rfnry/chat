# rfnry/chat-client-react

React client for rfnry/chat. Any identity role — `UserIdentity`, `AssistantIdentity`, `SystemIdentity` — can connect through this client. The docs below describe the common case (a human user in a browser tab) but the same API supports, for example, an in-browser AI assistant or an embedded system identity; pass the appropriate `identity` to `ChatProvider`.

## Proactive invites

When another participant adds this connected identity to a thread, the provider
receives a transient `thread:invited` frame from the server's inbox room,
hydrates the thread metadata into the store, auto-joins the thread room, and
invalidates the `['chat', 'threads']` query. Apps can observe the event via an
optional callback:

```tsx
<ChatProvider
  url="http://chat.internal"
  authenticate={async () => ({ headers: { authorization: 'Bearer …' } })}
  onThreadInvited={(thread, addedBy) => {
    // Show a toast, navigate to the thread, play a sound, etc.
  }}
>
  ...
</ChatProvider>
```

The `onThreadInvited` callback receives only `(thread, addedBy)` for
ergonomics — the invitee identity is usually implicit (it's the connected
user). **For the full frame including `addedMember`** — useful for group
chats or when you need to distinguish who was added from who added them —
use the `useInviteHandler` hook, which mirrors Python's `@on_invited`:

```tsx
import { useInviteHandler } from '@rfnry/chat-client-react'

function InviteToaster() {
  useInviteHandler((frame) => {
    // frame.thread, frame.addedMember, frame.addedBy
    toast(`${frame.addedBy.name} added ${frame.addedMember.name}`)
  })
  return null
}
```

**To opt out of auto-join**, pass `autoJoinOnInvite={false}` to
`ChatProvider`. The provider will hydrate thread metadata and fire
`onThreadInvited` / `useInviteHandler` listeners, but will not call
`client.joinThread(...)`; you're responsible for deciding whether to join
(e.g. based on a policy check inside `useInviteHandler`). This mirrors
Python's `auto_join_on_invite=False` opt-out.

```tsx
<ChatProvider url="…" authenticate={…} autoJoinOnInvite={false}>
  …
</ChatProvider>
```

## Default dispatch filters

Handler hooks (`useMessageHandler`, `useToolCallHandler`, `useHandler`, etc.) apply two filters before firing, matching the Python client's behavior:

- Events authored by this client's own identity are skipped (no self-triggering).
- Events with a non-null `recipients` list that doesn't include this identity's id are skipped.

Both filters are inert when the client has no `identity` configured. To bypass the filters on a single handler (audit loggers, moderation tooling), pass `{ allEvents: true }`:

```tsx
useMessageHandler(threadId, (event) => {...}, { allEvents: true })
```

## Who am I?

`useIdentity()` returns the identity this client is connected as (or `null` if none was configured):

```tsx
import { useIdentity } from '@rfnry/chat-client-react'

const identity = useIdentity()
if (identity?.role === 'user') { ... }
```

## Proactive helper

`ChatClient.openThreadWith({ message, invite?, threadId?, tenant?, metadata? })` composes create-or-fetch-thread → optional add-member → join → send-message into one call. Returns `{ thread, event }`. Mirrors Python's `client.open_thread_with(...)`.

```ts
const client = useChatClient()
const { thread } = await client.openThreadWith({
  message: [{ type: 'text', text: 'ping' }],
  invite: bob,
})
```

## Error handling

Socket failures throw `SocketTransportError` (with `code` and `message`).
HTTP failures throw `ChatHttpError`, or one of its subclasses:
`ThreadNotFoundError`, `ThreadConflictError`, `ChatAuthError`. Catch them
separately.

```ts
import {
  ChatAuthError,
  ChatHttpError,
  SocketTransportError,
  ThreadConflictError,
  ThreadNotFoundError,
} from '@rfnry/chat-client-react'

try {
  await client.getThread('th_missing')
} catch (e) {
  if (e instanceof ThreadNotFoundError) { /* ... */ }
  else if (e instanceof ChatAuthError) { /* ... */ }
  else if (e instanceof ChatHttpError) { /* ... */ }
}

try {
  await client.joinThread(threadId)
} catch (e) {
  if (e instanceof SocketTransportError) {
    console.error(e.code, e.message)
  }
}
```

## Reconnecting with new options

`ChatClient.reconnect({ url?, authenticate?, identity?, path?, socketPath?, fetchImpl? })`
tears down the REST and socket transports and rebuilds them with the supplied
options (any option omitted keeps its current value). This mirrors Python's
`ChatClient.reconnect(...)` — the method is URL-switchable without remounting
the `ChatProvider`.

Listeners registered via `client.on(event, handler)` are preserved: the client
keeps an internal registry and re-attaches them to the new socket after it
connects. Consumers do **not** need to re-register handlers.

```ts
await client.reconnect({ url: 'https://chat.staging.internal' })
// prior `client.on('event', handler)` subscriptions still fire.
```
