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

## Server-side handlers

The server exposes a generic dispatcher so you can react to any event type directly from the server process. Handlers take `(ctx, send)` and may either observe (no yield) or emit events (yield from `send`). Emitted events are authored by the server's `SystemIdentity`.

```python
@server.on("message")
async def audit(ctx, send):
    logger.info(f"[{ctx.thread.id}] {ctx.event.author.name}: {ctx.event.content}")

@server.on_tool_call("get_company_stock")
async def handle_stock(ctx, send):
    ticker = ctx.event.tool.arguments["ticker"]
    price = await stock_service.quote(ticker)
    yield send.tool_result(ctx.event.tool.id, result={"price": price})

@server.on("thread.member_added")
async def welcome(ctx, send):
    yield send.message(content=[TextPart(text=f"Welcome {ctx.event.member.name}")])
```

- `@server.on(event_type)` — observe or emit events of any type.
- `@server.on_tool_call(name)` — sugar that wraps execution in a `Run` and filters to `tool.call` events with matching `tool.name`.
- `@server.on_message()` / `@server.on_reasoning()` / `@server.on_tool_result()` — sugar shortcuts.

Loops are prevented automatically: handlers never re-trigger on events they themselves authored, and a chain-depth cap (`MAX_HANDLER_CHAIN_DEPTH`, default 8) limits recursion.

## Watchdog

If a client calls `run:begin` and never calls `run:end` (process crash, network drop, handler bug), the run would otherwise sit at `status=running` forever. Start the watchdog on app startup to sweep stale runs and mark them `failed(timeout)`:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    await chat_server.start()
    yield
    await chat_server.stop()

app = FastAPI(lifespan=lifespan)
```

Configure via `ChatServer(..., run_timeout_seconds=120, watchdog_interval_seconds=30)`. The sweep queries for runs with `status IN ('pending', 'running') AND started_at < now() - run_timeout_seconds` and transitions each to `failed` with error `code=timeout`, broadcasting `run.failed` so connected clients drop the run from their active-runs state.

## Socket API surface

- `thread:join`, `thread:leave` — room membership + history replay on join.
- `message:send` — send a `message` event (legacy path, kept for compatibility).
- `event:send` — generic ingress for `tool.call`, `tool.result`, `reasoning`.
- `run:begin`, `run:end` — client-driven run lifecycle for observability wrappers.
- `run:cancel` — cooperative cancel from any authorized member.
- `stream:start`, `stream:delta`, `stream:end` — relay streaming frames from a client to the thread room.

## Inbox rooms

Every authenticated socket is auto-joined to a room named `inbox:<identity_id>` on connect, scoped to its tenant namespace. When a member is added to a thread via REST (`POST /threads/:id/members`), the server broadcasts a transient `thread:invited` frame to the new member's inbox room in addition to the normal `members:updated` emit on the thread room. Clients use this to hydrate thread metadata and auto-join the thread without any prior socket subscription.

The frame carries `{thread, added_member, added_by}`. Self-adds (`added_member.id == added_by.id`, e.g. the creator auto-joining their own new thread) are suppressed.

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
