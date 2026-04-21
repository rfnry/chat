# customer-support example

A simplified port of the real `airfilterbuy-cs/cs-agent` onto the new API. Two architecturally independent pieces run inside one FastAPI process:

1. **Chat server** (`server.py`) — holds threads, members, events, runs. Has an observability handler that mirrors every event to a simulated sink.
2. **Agent** (`agent.py`) — an `AssistantIdentity` that connects to the server as an external participant using `rfnry-chat-client`. Uses Anthropic (if `ANTHROPIC_API_KEY` is set) for turn logic and owns its own tools (`order_lookup`, `escalate_to_human`).

They share a FastAPI process for convenience. In production you'd split them into two services; the architecture is already decoupled.

## Layout

```
src/
  main.py          FastAPI lifespan — starts chat server, schedules agent ChatClient
  server.py        ChatServer + @server.on("*") observability mirror
  agent.py         rfnry-chat-client ChatClient + @client.on_message handler
  tools.py         Tool definitions + fake executors (order_lookup, escalate_to_human)
  observability.py Simulated sink (stdout JSON)
  auth.py          Token-based auth — user tokens and assistant token
  settings.py      Env-driven config
  db.py            LazyStore + pool factory
```

## What this demonstrates vs the old API

**Old (`cs-agent/src/handler.py`):**
```python
# Handler lives inside the chat server process.
# register_assistant binds a handler fn to an assistant id.
chat.register_assistant(assistant_id, make_handler(anthropic, clients))

# Handler signature: (ctx, send) async generator.
# ctx.events(), ctx.thread, ctx.run, ctx.assistant provided by the server.
async def handle(ctx, send):
    history = await ctx.events(limit=200)
    # ... call Anthropic, yield events ...
```

The problem: the agent is *inside* the server. Two responsibilities (transport + AI) in one deployable. No way to scale the agent independently. No way to swap in a different agent implementation without restarting the server.

**New (`src/agent.py`):**
```python
# Agent is a ChatClient — connects to the server like any other participant.
client = ChatClient(base_url="http://chat-server", identity=me, authenticate=...)

# Same (ctx, send) shape, but now on the client side.
@client.on_message(in_run=True)
async def respond(ctx, send):
    history_page = await client.rest.list_events(ctx.event.thread_id, limit=200)
    # ... call Anthropic, yield events (which emit via socket event:send) ...
```

Same handler shape. Different deployment model. The agent can:
- Run on a different host.
- Be replaced with a LangGraph / OpenAI-Agents / custom orchestrator with zero server changes.
- Scale horizontally (N agent instances behind a round-robin) — the `runs_active_per_actor` unique index still keeps per-actor turn ordering sane.

## What the server now does

The server is no longer the AI driver. It is a pure hub that:

- Persists + broadcasts events.
- Tracks Run lifecycle (start/end/timeout via the watchdog).
- Exposes a narrow dispatcher for side effects — in this example, every event goes to the observability mirror.

## Run

```bash
# 1. Postgres (reuse the chat server's docker):
cd ../../../packages/server-python
docker compose -f docker-compose.test.yml up -d

# 2. Set your Anthropic key (optional — stubs if missing):
export ANTHROPIC_API_KEY=sk-ant-...

# 3. This example:
cd ../../examples/server-python/customer-support
uv sync
uv run uvicorn src.main:asgi --host 0.0.0.0 --port 8000
```

The agent auto-connects after startup. Logs show:
```
cs.main | chat server + watchdog running
cs.main | agent client scheduled connect to http://127.0.0.1:8000
cs.main | agent connected
```

## Client flow (React)

```typescript
const client = new ChatClient({
  url: 'http://localhost:8000',
  authenticate: async () => ({ headers: { authorization: 'Bearer u_alice' } }),
})

// Create thread, add Alice and the agent as members.
const thread = await client.createThread({ tenant: {} })
await client.addMember(thread.id, { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} })
await client.addMember(thread.id, {
  role: 'assistant',
  id: 'cs-agent',
  name: 'Customer Support',
  metadata: {},
})

await client.connect()
await client.joinThread(thread.id)

// Send a message addressed at the agent.
await client.sendMessage(thread.id, {
  clientId: 'c1',
  content: [{ type: 'text', text: "Where's my order ORD-1001?" }],
  recipients: ['cs-agent'],
})

// The agent receives it (on_message handler fires),
// calls Anthropic, yields tool.call(order_lookup), yields tool.result,
// yields final message — all inside a server-tracked Run.
```

## Observability sink

`observability.send_to_sink` is a stub that logs to stdout as structured JSON:

```
cs.observability | obs.event {"thread_id": "...", "event_type": "message", "author_id": "u_alice", "author_role": "user", ...}
cs.observability | obs.event {"thread_id": "...", "event_type": "run.started", ...}
cs.observability | obs.event {"thread_id": "...", "event_type": "tool.call", "tool_name": "order_lookup", ...}
cs.observability | obs.event {"thread_id": "...", "event_type": "tool.result", ...}
cs.observability | obs.event {"thread_id": "...", "event_type": "message", "author_id": "cs-agent", ...}
cs.observability | obs.event {"thread_id": "...", "event_type": "run.completed", ...}
```

Swap with Datadog / Honeycomb / whatever — it's a single-function boundary.
