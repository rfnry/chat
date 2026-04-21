# monitoring-assistant — React receiver

Minimal React app that logs in as a user and renders every thread they belong
to. The point is to demonstrate that when the `monitoring-assistant` Python
backend pages a user, the invite and the first message arrive in real time via
the `thread:invited` frame — no refresh, no poll.

## What it does

- Connects as `u_alice` via `<ChatProvider url="http://localhost:8000" ...>`.
- Passes an `onThreadInvited` callback to the provider that logs each invite
  arrival.
- Renders every thread visible to the user via `useThreads`, with the most
  recent message per thread pulled from `useThreadEvents`.
- When the Python agent calls `open_thread_with(user=u_alice, ...)`, the server
  broadcasts `thread:invited` to `inbox:u_alice`; the provider hydrates the
  thread meta, auto-joins the thread room, invalidates the threads query, and
  fires the `onThreadInvited` callback. The thread appears in this UI instantly.

## Run

1. Start a chat server (e.g. the `customer-support` example's server on port 8000).
2. Start the Python `monitoring-assistant` backend pointing at that chat server.
3. Start this React app (however the repo's react examples are built — consult
   the top-level `examples/react/` README for the canonical invocation).
4. Trigger a webhook:

   ```bash
   curl -X POST http://localhost:9100/agent/ping-user \
     -H "content-type: application/json" \
     -d '{"message": "Hello from the agent", "user_id": "u_alice", "user_name": "Alice"}'
   ```

5. The new thread appears in this UI immediately with the bot's message.

## What to watch

- Browser console: `[invited] th_... by a_monitor` as soon as the agent invites you.
- The thread list hydrates without polling.
- Subsequent messages update the UI via the normal `event` socket path (thanks to auto-join).
