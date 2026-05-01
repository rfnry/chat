# @rfnry/chat-client-react

React client for rfnry/chat. Hooks-shaped, render-granular, fully typed. `<ChatProvider>` plus 16 `useChatX` hooks cover everything: connection state, thread lifecycle, history, members, presence, work-in-progress indicators, file uploads. The same hook surface works for human users, in-browser AI assistants, and embedded system identities — pass the appropriate `identity` and the rest is identical.

If you've used Vercel AI SDK and want something that does multi-participant rooms instead of single-turn completions, this is the equivalent for that shape of product. The mental model mirrors the Python client one-to-one, so a frontend dev and a backend agent dev reading each other's code never have to translate.

## Getting Started

```bash
npm install @rfnry/chat-client-react
```

```tsx
import { ChatProvider, useChatClient, useChatHistory, useChatSession } from '@rfnry/chat-client-react'

function App() {
  return (
    <ChatProvider url="http://chat.internal" identity={{ role: 'user', id: 'u_1', name: 'Alice', metadata: {} }}>
      <Thread id="th_1" />
    </ChatProvider>
  )
}

function Thread({ id }: { id: string }) {
  const client = useChatClient()
  const session = useChatSession(id)
  const events = useChatHistory(id)

  if (session.status !== 'joined') return <p>{session.status}…</p>
  return (
    <>
      {events.map((e) => <Bubble key={e.id} event={e} />)}
      <button onClick={() => client.sendMessage(id, { content: [{ type: 'text', text: 'hi' }] })}>send</button>
    </>
  )
}
```

`useChatSession(id)` drives the join + replay; `useChatHistory(id)` subscribes to the event log; `client.sendMessage(...)` returns a `Promise<Event>` you can `await` if you want optimistic UI hooks. Every hook is independent — adding `useChatPresence()` or `useChatIsWorking(id)` doesn't wake the others.

## Features

**Symmetric mental model with the backend.** `useChatHandlers().on.message(fn)` mirrors Python's `@client.on_message()`. `client.withRun(threadId, async (send) => …)` mirrors Python's `async with client.send(thread_id) as send:`. The same identity model, same event types, same recipients filter applies. A frontend dev who writes a chat reaction handler and a Python dev who writes the agent that reacts read the same shape — the only difference is whether you wrote it as a hook or a decorator.

**Render-granular by design.** Each hook subscribes to one slice of the zustand store. `useChatMembers(id)` only re-renders on member changes; `useChatHistory(id)` only on new events; `useChatIsWorking(id)` only when a boolean flips. Splitting the surface this way means a typing-indicator component costs ~2 renders per turn, not 20. The page-hook pattern (compose your view's hooks into one `usePageX` and consume the ViewModel from the component) keeps UI and chat behavior cleanly separated without sacrificing this granularity.

**Proactive flows are first-class.** When another participant adds the connected identity to a thread, `<ChatProvider>` auto-receives the `thread:invited` frame from the server's inbox room, hydrates the thread metadata into the store, joins the thread room, and invalidates the threads query. Apps observe via `onThreadInvited` (lossy, ergonomic) or `useChatHandlers().on.invited(fn)` (the full parsed frame including who was added and who added them). Build "agent DMs the user" without polling.

**Streaming, transcript, history — three views, one truth.** `useChatTranscript(id)` is the render-ready merged feed: persisted events interleaved with in-flight streaming partials, chronologically sorted. `useChatHistory(id)` is persisted events only (audit, export). `useChatStreams(id)` is partials only (typing indicators, live cursors). Pick the slice that matches the cost you want to pay; the store maintains all three coherently.

**Suspense + TanStack Query under the hood.** `useChatSuspenseThread(id)` integrates with React's Suspense boundary; `useChatThreads(opts)` returns a `UseQueryResult` you can pair with mutations and invalidations. `useQueryClient` and `QueryClient` are re-exported so you don't manage two query clients.

**Frame-level handlers with parse-once delivery.** `useChatHandlers()` exposes typed registration for `message`, `reasoning`, `toolCall`, `toolResult`, `anyEvent`, `invited`, `threadUpdated`, `membersUpdated`, `runUpdated`, `presenceJoined`, `presenceLeft`, plus a generic `event(type, fn)` escape hatch. Default filters skip self-authored events and recipient-mismatched ones; opt out with `{ allEvents: true }`. Every incoming wire frame is parsed once at the provider, regardless of how many handler hooks are mounted.

## License

MIT — see [`LICENSE`](./LICENSE).
