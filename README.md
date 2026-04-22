## rfnry-chat

A multi-tenant chat hub where humans and AI agents participate as equal
members of a thread. The server is a pure routing hub; AI agents run as
external services and connect via a `ChatClient` the same way browsers do.

### Packages

- [`packages/server-python`](./packages/server-python) — FastAPI + Socket.IO
  chat server. Threads, members, events, runs, tenant scoping, authentication,
  authorization.
- [`packages/client-python`](./packages/client-python) — Python client.
  Backend agents (LLM-driven assistants, webhook-triggered monitors) connect
  through this.
- [`packages/client-react`](./packages/client-react) — React client. Hooks +
  `<ChatProvider>`, built on zustand and TanStack Query.

### Features

- **Symmetric participation.** Humans and AI agents share the same identity
  model, the same socket API, and the same event log. A thread may be
  human-to-AI, human-to-human, AI-to-AI, or any mix.
- **Tool calls as events.** `tool.call` / `tool.result` are first-class
  events, not an out-of-band RPC. Any participant who knows a tool name can
  respond; multiple responders are correlated by tool id.
- **Streaming.** `stream:start` / `stream:delta` / `stream:end` relay token
  streams from any participant to the thread room.
- **Proactive agents (inbox rooms).** Agents can open a thread and ping a
  specific user without that user having joined anything yet. On connect,
  every socket is auto-joined to a per-identity `inbox:<id>` room; when
  someone is added as a thread member, the server emits a transient
  `thread:invited` frame to that room. Both clients handle it: the Python
  client exposes `@client.on_invited()` and `client.open_thread_with(...)`;
  the React `<ChatProvider>` hydrates the thread, auto-joins, and fires an
  optional `onThreadInvited` callback.
- **Multi-server agents.** `ChatClient.reconnect(base_url=...)` switches
  URLs at runtime; `ChatClientPool` holds one connected client per chat
  server for agents serving many hosts from one process.

### Examples

- [`examples/python/stock-tool`](./examples/python/stock-tool) — server-side
  tool handlers only.
- [`examples/python/customer-support`](./examples/python/customer-support) —
  external AI agent (Anthropic) reacting to user messages.
- [`examples/python/monitoring-assistant`](./examples/python/monitoring-assistant) —
  standalone webhook-driven agent (no chat server; pairs with
  [`examples/react/monitoring-assistant`](./examples/react/monitoring-assistant)
  as the receiver).

### License

MIT — see [`LICENSE`](./LICENSE).
