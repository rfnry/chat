# rfnry/chat-client-react

React client for rfnry/chat.

## Proactive invites

When another participant adds this connected user to a thread, the provider
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

The callback receives only `(thread, addedBy)`. The invitee identity is
implicit (it's the connected user), so it's dropped — unlike the Python
client's `@on_invited` which hands over the full `ThreadInvitedFrame(thread,
added_member, added_by)`. If you need `added_member` in React, read it off the
socket directly via `client.on('thread:invited', ...)`.

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
