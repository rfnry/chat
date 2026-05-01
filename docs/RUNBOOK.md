# rfnry-chat — operator runbook

How rfnry-chat behaves under disconnect, reconnect, and replay. Read this before running it in production with a non-trivial user base.

## The disconnect → reconnect → replay flow

```
[client connected] ─── socket alive ───────▶ [event broadcast] ─▶ store
       │
       │  network drop / tab backgrounded / server restart
       ▼
[disconnected]
       │
       │  socket.io re-establishes
       ▼
[reconnecting] ──▶ joinThread(threadId, since=last-event)
                                │
                                ▼
                         server replay
                                │
                          ┌─────┴─────┐
                          │           │
                  replay covers     replay capped at N
                  the gap fully     events (replay_truncated=true)
                          │           │
                          ▼           ▼
                   [joined]      [joined, gap exists]
                                       │
                                       ▼
                          consumer calls client.backfill(...)
                          to fill the hole
```

## What can go wrong, and what the SDK does about it

### Long disconnect → silent gap (Case 1)

**What:** Browser tab backgrounded for hours. On reconnect, the server's replay window (`replay_cap`, default 500) doesn't reach back to where the client left off. Server returns `replay_truncated=true`.

**SDK signal:** `useChatSession(threadId).replayTruncated === true` (React) / `result["replay_truncated"]` from `client.join_thread(...)` (Python).

**SDK fix:** call `client.backfill(threadId, before=oldest_local_event)` to fetch older events page-by-page. React: use `useChatBackfill(threadId)` which wires this up against the local store.

**Operator lever:** raise `ChatServer(replay_cap=...)` if your typical reconnect window exceeds 500 events. Trade-off: larger replays mean larger payloads on rejoin.

### Mid-stream disconnect → stuck partial (Case 2)

**What:** Connection drops while the assistant is streaming tokens. `stream:end` and the final `MessageEvent` may or may not reach the client. Without intervention, the streaming partial UI shows the assistant "still typing" forever.

**SDK fix:** automatic. The chat store now drops streaming partials when a terminal run event (`run.completed | run.failed | run.cancelled`) arrives for that runId. The watchdog reaps stalled runs server-side (`run_timeout_seconds`, default 60s); the resulting `run.failed(timeout)` event flows through the standard event broadcast and clears the partial on arrival.

**Operator lever:** tune `ChatServer(run_timeout_seconds=…, watchdog_interval_seconds=…)` for your typical assistant turn time. Default 60s is generous for chat workloads.

### Tenant change mid-thread (Case 3)

**What:** User has a thread URL bookmarked. Their tenant scope changes (admin moved them, thread migrated). They reload. Server returns `not_found` on join — a deliberate security choice to prevent leaking thread existence across tenants.

**SDK signal:** `SocketTransportError(code='not_found' | 'forbidden')` thrown from `joinThread`. Surfaces as `useChatSession.error` (typed).

**Application responsibility:** catch the typed error and render an appropriate UI:

```tsx
const session = useChatSession(threadId)
if (session.status === 'error' && session.error instanceof SocketTransportError) {
  if (session.error.code === 'not_found') return <NoAccessFallback />
  if (session.error.code === 'forbidden') return <PermissionDeniedFallback />
}
```

The SDK does not navigate or render fallbacks itself.

**Operator lever:** if the existence-hiding policy is too strict for your product, talk to us before relaxing it on the server — it's a deliberate security trade-off.

### Identity change / re-auth (Case 4)

**What:** User logs out, another user logs in on the same browser session. Without explicit handling, in-memory state from the old user (cached threads, members, presence) leaks to the new user's view.

**SDK fix:** automatic. `<ChatProvider>` watches the `identity` prop. When it changes, the provider:

1. Resets the chat store.
2. Resets the presence slice.
3. Reconnects the underlying transports with the new identity.
4. Invalidates the `['chat']` TanStack queries.

**Opt-out:** `<ChatProvider resetOnIdentityChange={false}>` for advanced consumers who handle re-auth themselves.

The `<ChatProvider key={identity.id}>` pattern (yard examples use it) still works and remains the simplest mental model. The auto-reset is defense-in-depth.

### Broadcast failure → sender's UI doesn't see their own message (Case 5)

**What:** Sender calls `sendMessage`, REST returns 200, but the broadcast fails (sticky-session misroute, broker error). The sender's local store never sees the event. Refresh required.

**SDK fix:** automatic. Both clients optimistically dispatch the canonical event from REST/socket-ack into the local handler dispatch path. If the broadcast also arrives later, dispatcher dedup (LRU of last 256 event ids) prevents handlers from firing twice.

**Operator lever:** none needed. If you're seeing systemic broadcast failures, look at your Socket.IO sticky-session config and your broker (Redis Streams adapter, etc).

## Testing the failure modes

The SDK and server expose enough configuration to repro the failures in <1s test runs. Key levers:

- `ChatServer(replay_cap=N)` — set N=5 in tests to repro replay-truncated by appending 6 events.
- `ChatServer(run_timeout_seconds=0.5, watchdog_interval_seconds=0.1)` — repro watchdog reap in under a second.
- `client.socket.rawSocket.disconnect()` — simulate mid-stream connection drop without waiting for a real network event.
- `replay_max` semantics: cap is per-page; tests don't need 200+ events to trigger truncation.

See `tests/scenarios/` (when populated) for canonical reproductions of each case.

## What's still on the SDK roadmap

- A `<ChatErrorBoundary>` component that catches `SocketTransportError`, `ChatHttpError`, and the typed subclasses to centralize the access-denied UX.
- Server-emitted heartbeat for liveness detection (alternative to optimistic insert; not yet justified by a real failure case).
- Per-tenant `replay_cap` configuration if a real ops case demands it.

When in doubt, file an issue with the failure mode you observed and the closest case above.
