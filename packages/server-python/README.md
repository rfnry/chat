# rfnry-chat-server

Python server for rfnry/chat. A multi-tenant chat hub over FastAPI + Socket.IO where humans and AI agents participate as equal members of a thread. The server owns threads, membership, event history, run lifecycle, and tenant scoping. It does not execute agent logic — agents run in their own services and connect via `rfnry-chat-client`.

## Install

```bash
pip install rfnry-chat-server
```

## Minimal server

```python
from fastapi import FastAPI
from rfnry_chat_server import (
    AuthenticateCallback,
    ChatServer,
    HandshakeData,
    Identity,
    PostgresChatStore,
    UserIdentity,
)
import asyncpg


async def authenticate(hs: HandshakeData) -> Identity | None:
    token = hs.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return await resolve_user_from_token(token)


async def main() -> None:
    pool = await asyncpg.create_pool(dsn="postgresql://...")
    store = PostgresChatStore(pool=pool)
    server = ChatServer(store=store, authenticate=authenticate)

    app = FastAPI()
    app.include_router(server.router, prefix="/chat")
    asgi = server.mount_socketio(app)

    import uvicorn
    await uvicorn.Server(uvicorn.Config(asgi, host="0.0.0.0", port=8000)).serve()
```

## Server-side tool handlers

The server exposes a narrow dispatcher so you can answer `tool.call` events directly from the server process, without needing a separate agent service. Handlers run under a server-owned `Run` authored by `SystemIdentity`.

```python
@server.on_tool_call("get_company_stock")
async def handle_stock(ctx):
    ticker = ctx.event.tool.arguments["ticker"]
    return {"price": await stock_service.quote(ticker)}
```

Any authenticated thread member — human or AI agent — can emit a `tool.call` event with `tool.name == "get_company_stock"`, and the server publishes a matching `tool.result` to the caller automatically.

## Socket API surface

- `thread:join`, `thread:leave` — room membership + history replay on join.
- `message:send` — send a `message` event (legacy path, kept for compatibility).
- `event:send` — generic ingress for `tool.call`, `tool.result`, `reasoning`.
- `run:begin`, `run:end` — client-driven run lifecycle for observability wrappers.
- `run:cancel` — cooperative cancel from any authorized member.
- `stream:start`, `stream:delta`, `stream:end` — relay streaming frames from a client to the thread room.

## Scope

The server does:

- Authenticate sockets and REST requests.
- Enforce authorization per-action.
- Scope threads by tenant via `namespace_keys`.
- Persist threads, members, events, runs via the `ChatStore` protocol.
- Broadcast events, thread updates, member updates, run transitions, stream frames to the room.

The server does not:

- Drive agent logic (no `register_assistant`, no `RunExecutor`).
- Fan out `recipients` to trigger anyone (recipient filtering is a semantic hint consumed by each participant).
- Mediate tool execution beyond the narrow `on_tool_call` registry.

Agents live in separate services and connect via `rfnry-chat-client`.

## Design

See [`docs/plans/2026-04-21-chat-refactor-design.md`](../../docs/plans/2026-04-21-chat-refactor-design.md) for the full design narrative.

## Development

```bash
docker compose -f docker-compose.test.yml up -d
uv sync --extra dev
uv run poe dev
```
