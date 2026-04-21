# monitoring-assistant example

A standalone AI agent backend. **Does not ship a chat server.** It connects to
one (or many) external `rfnry-chat-server` hosts as an `AssistantIdentity` and
reacts to webhooks from a monitoring system by proactively opening a thread
with a specific user.

## Difference from the other examples

| Example            | Ships a chat server? | How agent is triggered            |
|--------------------|----------------------|-----------------------------------|
| stock-tool         | Yes                  | Reacts to incoming tool.calls     |
| customer-support   | Yes                  | Reacts to incoming user messages  |
| **monitoring-assistant** | **No**         | **External webhook → proactively opens thread** |

This is the reference shape for deployments where the agent runs on its own
host, talks to one or more chat servers over the network, and is driven by
external systems (monitoring alerts, cron jobs, queue consumers).

## What it does

1. Starts a FastAPI service on `PORT` (default `9100`) exposing `POST /agent/ping-user`.
2. Maintains a `ChatClientPool` — one connected `ChatClient` per chat-server URL.
3. On each webhook:
   - Picks or creates a `ChatClient` for the requested `chat_server_url`.
   - Calls `client.open_thread_with(...)` which creates (or reuses) a thread,
     invites the target user, joins the thread room, and sends the alert.
4. Subsequent messages from the user in that thread trigger `@on_message` — the
   minimal implementation just acknowledges; swap it for an LLM in real use.

## Layout

```
src/
  main.py        FastAPI app + /agent/ping-user webhook
  agent.py       ChatClient factory + @on_invited / @on_message handlers
  settings.py    env-driven config
```

## Run

Prerequisite: a running `rfnry-chat-server` reachable on `DEFAULT_CHAT_SERVER_URL`.
The simplest way to get one: run the `customer-support` example (which ships a
server), then point this agent at its port:

```bash
# Terminal 1 — chat server (from customer-support example)
cd examples/python/customer-support && uv sync && uv run uvicorn src.main:app --port 8000

# Terminal 2 — standalone agent
cd examples/python/monitoring-assistant && uv sync
AGENT_TOKEN=<same-token-the-server-accepts> \
DEFAULT_CHAT_SERVER_URL=http://localhost:8000 \
  uv run uvicorn src.main:app --port 9100
```

## Trigger a proactive ping

```bash
curl -X POST http://localhost:9100/agent/ping-user \
  -H "content-type: application/json" \
  -d '{
    "message": "Disk usage on api-03 crossed 90%. Acknowledge?",
    "user_id": "u_alice",
    "user_name": "Alice"
  }'
```

Response: `{"thread_id": "th_...", "event_id": "evt_..."}`.

Optional fields:
- `chat_server_url` — override the target chat server (enables multi-server fan-out).
- `thread_id` — reuse an existing thread instead of creating a new one.

## Situation A vs Situation B

**A — Fixed URL.** One agent host talks to exactly one chat server. Set
`DEFAULT_CHAT_SERVER_URL` in the environment and never pass `chat_server_url`
in the webhook payload. The pool ends up with a single entry.

**B — Multi-server switching.** The webhook payload chooses the chat server
at call time. The pool grows lazily as new URLs arrive. Useful when the agent
serves many customer workspaces, each with its own chat-server deployment.

Both modes work with the same code path.

## Receiving side

The `examples/react/monitoring-assistant/` example is a minimal React client that
logs in as a user and shows any thread the agent opens for them. It
demonstrates that `thread:invited` arrives in real time — no polling, no
refresh.
