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
  main.py      FastAPI app + lifespan wiring (InMemoryChatStore, no auth)
  chat.py      create_chat_server() + @server.on_* handlers
```

## Run

```bash
cd examples/python/stock-tool
uv sync
uv run uvicorn src.main:asgi --host 0.0.0.0 --port 8100
```

No database, no auth, no external services — storage is in-process dicts, identity is whatever the client sends in the handshake or the `x-rfnry-identity` header.

## Available tools

- `check_stock({ sku })` → `{ sku, available }` or `{ error: sku_not_found }`
- `shipping_status({ shipment_id })` → shipment row or `{ error: shipment_not_found }`
