# rfnry-chat-server

A real-time chat hub for humans and AI agents over FastAPI + Socket.IO. The server owns threads, membership, event history, runs, and tenant scoping. AI agents are not embedded — they live in their own services and connect through the same socket protocol as browsers, on equal footing with users.

This package is for teams building chat-shaped products where the AI is a first-class participant: a teammate that joins channels, gets DMed, can DM back, can hold tools, can hand off to another agent, and can be paused or cancelled mid-thought. If your model is "user → backend → LLM call → response" you'll find what's here unfamiliar; if your model is "many participants in a room, some of them happen to think with neural nets," you're home.

## Getting Started

```bash
pip install rfnry-chat-server
```

```python
from fastapi import FastAPI
import asyncpg
from rfnry_chat_server import ChatServer, HandshakeData, Identity, PostgresChatStore

async def authenticate(hs: HandshakeData) -> Identity | None:
    token = hs.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return await resolve_user_from_token(token)

pool = await asyncpg.create_pool(dsn="postgresql://...")
store = PostgresChatStore(pool=pool)
server = ChatServer(store=store, authenticate=authenticate)

app = FastAPI(lifespan=server.lifespan)
server.mount(app, path="/chat")
```

The mounted app exposes the REST surface (`/threads`, `/events`, `/members`, `/runs`) and a Socket.IO namespace at `/chat/ws`. Both use the same authentication callback.

## Features

**Symmetric participation.** Humans, AI assistants, and system identities are all just `Identity` rows. They share the same socket protocol, the same event log, the same membership model. A thread is just a room of participants — human-to-AI, human-to-human, AI-to-AI, or any mix is the same code path. Compare to providers where the AI lives outside the conversation and gets bolted on per-request.

**Proactive AI, not just reactive.** Every authenticated socket auto-joins an inbox room scoped to its identity. When something — a webhook, a cron, another agent — adds an identity to a thread, the server emits a transient `thread:invited` frame to that inbox. The receiving client (browser or backend agent) hydrates the thread and reacts. AI agents can open threads with users, ping them, run a workflow, and disappear — without those users having joined anything first.

**Tool calls as first-class events.** `tool.call` and `tool.result` are events in the same log as messages, correlated by tool id. Anyone in the thread who knows a tool name can publish a result; multiple responders are correlated by id. This collapses the usual "tool registry / RPC dispatcher" layer — tools are just events with a contract, and the server only routes them.

**Streaming with run lifecycle.** `stream:start` / `stream:delta` / `stream:end` relay token streams from any participant to the thread room. Streams are owned by a `Run` — a lightweight observability envelope tracking `pending → running → completed | failed | cancelled`. A watchdog reaps stale runs (configurable timeout) and transitions them to `failed(timeout)` so the UI never hangs on a dropped agent.

**Multi-tenant by default.** Configure `ChatServer(namespace_keys=[...])` and the Socket.IO namespace becomes a wildcard pattern, with each connection's tenant scope derived from the identity at handshake time. Threads, events, and broadcasts are isolated per-tenant at both the store and the socket layer. `NamespaceViolation` is a typed error you can catch and turn into 403s. The `matches()` helper composes tenant scopes for fine-grained access checks.

**Pluggable storage.** `ChatStore` is a `Protocol`. The package ships `InMemoryChatStore` (tests, prototyping) and `PostgresChatStore` (production, asyncpg-based). Anything implementing the protocol works — bring your own database. Schema for the Postgres impl ships in `store/postgres/schema.sql`; the in-memory impl is for fast iteration without the migration tax.

## License

MIT — see [`LICENSE`](./LICENSE).
