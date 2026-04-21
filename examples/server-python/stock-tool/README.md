# stock-tool example

A chat server with no AI agent. Human users connect via the React client, join a thread, and emit `tool.call` events to query stock levels and shipping status. The server answers with `tool.result` events authored by `SystemIdentity`.

The point: **the server is itself a participant**. It reacts to events it understands. There is no agent service running in the background.

## What it demonstrates

- `@server.on_tool_call("name")` — a narrow decorator that wraps the handler in a `Run` (`actor = SystemIdentity`), so every tool invocation produces a visible `run.started` / `run.completed` pair in the thread.
- `@server.on_message()` — a plain observer that just logs every message as it passes through. No `Run`, no emission.
- Run watchdog — started via `ChatServer.start()` in the FastAPI lifespan, sweeps stuck runs every 30s.

## Layout

```
src/
  main.py      FastAPI app + lifespan wiring
  chat.py      create_chat_server() + @server.on_* handlers
  auth.py      Token-in-header authentication callback
  db.py        LazyStore pattern (FastAPI module-import vs pool-in-lifespan)
```

## Run

```bash
# Postgres (reuse the chat server's docker):
cd ../../../packages/server-python
docker compose -f docker-compose.test.yml up -d

# This example:
cd ../../examples/server-python/stock-tool
uv sync
uv run uvicorn src.main:asgi --host 0.0.0.0 --port 8000
```

## Client flow (React)

```typescript
// Connect as a user
const client = new ChatClient({
  url: 'http://localhost:8000',
  authenticate: async () => ({ headers: { authorization: 'Bearer u_alice' } }),
})

// Create thread, become a member
const thread = await client.createThread({ tenant: {} })
await client.addMember(thread.id, { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} })
await client.connect()
await client.joinThread(thread.id)

// Emit a tool call from the UI
const me = { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} }
await client.emitEvent({
  type: 'tool.call',
  threadId: thread.id,
  author: me,
  createdAt: new Date().toISOString(),
  tool: { id: 'call_1', name: 'check_stock', arguments: { sku: 'FBA-MERV11-16x25x1' } },
})

// The server's on_tool_call handler fires:
//   → opens a Run (actor=system, triggered_by=u_alice)
//   → yields send.tool_result(tool_id='call_1', result={'sku': ..., 'available': 4820})
//   → server publishes the tool.result event
//   → the run completes

// React receives tool.result via useToolResultHandler(...)
```

## Available tools

- `check_stock({ sku })` → `{ sku, available }` or `{ error: sku_not_found }`
- `shipping_status({ shipment_id })` → shipment row or `{ error: shipment_not_found }`

## What this replaces vs the old API

The old API didn't have this pattern at all — the only way to "run tool logic server-side" was to register an `AssistantIdentity` handler (`@server.assistant("stock-bot")`) and invoke it via `POST /invocations` with that bot's id. That pretended there was an AI agent where there wasn't one.

In the new API, the server **is** the tool executor. No fake assistant identity. No invocation RPC. Just an event stream where whoever owns the tool name answers.
