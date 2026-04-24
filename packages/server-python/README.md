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
    asgi = server.mount(app)

    import uvicorn
    await uvicorn.Server(uvicorn.Config(asgi, host="0.0.0.0", port=8000)).serve()
```

## Production deployment

When streaming is the dominant workload — most events are `stream:delta` frames carrying a few tens of bytes of LLM tokens — disable WebSocket per-message compression at the ASGI server. Uvicorn enables `permessage-deflate` by default, which adds CPU overhead per frame with near-zero size benefit on payloads below the deflate window. Larger payloads (history replay over REST) compress fine at the HTTP layer.

```python
await uvicorn.Server(uvicorn.Config(
    asgi,
    host="0.0.0.0",
    port=8000,
    ws_per_message_deflate=False,
)).serve()
```

## Postgres connection pool sizing

`PostgresChatStore` takes an `asyncpg.Pool` you build yourself. asyncpg's
default (`min_size=10, max_size=10`) is a reasonable starting point for
small to medium deployments, but the right size depends on your workload's
peak concurrent connection demand. The pool **blocks on `acquire()` when
exhausted** — under-sizing means requests serialize through pool waits,
which looks like a slow server.

Connection demand by code path (per uvicorn worker):

- **Per published event**: 1 connection for `append_event`, plus 1 if
  `namespace_keys` is set and the caller didn't pass `thread=...` (one-time
  `get_thread` lookup before the parallel write+broadcast). Typical: 1-2
  per publish.
- **Per REST request**: 1-3 connections sequentially, depending on the
  endpoint (e.g. `POST /threads` does create-then-fetch; `GET /events`
  does one query).
- **Per `thread:join` history replay**: 1 connection.
- **Watchdog sweep**: N concurrent connections, where N is the number of
  stale runs found in one sweep. Each `end_run` does ~3 sequential
  acquisitions; the sweep parallelizes via `asyncio.gather`. With 100
  stale runs (e.g. after a crash burst), the sweep wants 100 connections
  for a brief window.

Sizing guidance per worker:

| Deployment | Suggested `max_size` | Rationale |
|---|---|---|
| Small (< 50 concurrent users, low message rate) | `10` (asyncpg default) | Steady-state demand under 5; default leaves headroom. |
| Medium (typical chat, < 500 users, watchdog rarely fires with > 10 stale runs) | `20-30` | Covers concurrent REST + publish + a moderate watchdog burst. |
| Large (1000+ users, frequent agent crashes producing stale runs) | `50-100` | Watchdog burst dominates; size for expected stale-run count + headroom. |

A few additional knobs:

- **`min_size`**: keep small (`1-5`). Idle deployments don't need to hold
  connections; asyncpg grows the pool on demand up to `max_size`.
- **PostgreSQL `max_connections`**: server-side cap. With N uvicorn workers
  each holding a pool of `max_size`, total DB connections = `N × max_size`.
  Stay well under PostgreSQL's `max_connections` (default 100). For
  high-worker-count deployments, front the pool with PgBouncer in
  transaction-pooling mode so each worker's pool reuses a smaller
  upstream connection set.
- **Streaming hot path doesn't pressure the pool**: `stream:delta` frames
  go straight to the Socket.IO room with no DB hit (the authorized thread
  is cached in the socket session at `stream:start`). High token rates
  don't translate to high pool demand.
- **`max_inactive_connection_lifetime`**: set this (e.g. `300` seconds) so
  asyncpg rotates idle connections before Postgres' `idle_in_transaction_session_timeout`
  or upstream NAT/load-balancer tables silently kill them. Without it,
  the first acquire after a long idle period surfaces the dropped
  connection as a confusing `InterfaceError` instead of transparently
  reconnecting.

Example pool construction:

```python
import asyncpg

pool = await asyncpg.create_pool(
    dsn="postgresql://...",
    min_size=2,
    max_size=20,  # sized for medium workload
    command_timeout=30,  # circuit-break long-running queries
    max_inactive_connection_lifetime=300,  # rotate idle conns every 5 min
)
store = PostgresChatStore(pool=pool)
```

## Auth callback caching

`authenticate` is called on every REST request. If your callback hits a
database, a JWT verifier with JWKS fetch, or any external auth service,
that's one extra network hop per request. Wrap it with `cached_authenticate`
to TTL-cache results by Authorization header:

```python
from rfnry_chat_server import ChatServer, cached_authenticate

async def my_authenticate(handshake):
    token = handshake.headers.get("authorization", "")
    return await my_auth_service.verify(token)  # slow

auth = cached_authenticate(my_authenticate, ttl_seconds=60.0, max_size=4096)
server = ChatServer(store=store, authenticate=auth)
```

Both successful (`Identity`) and failed (`None`) results are cached so an
attacker can't probe token validity by timing. For non-header auth schemes
(cookie, custom payload), pass `key=lambda hs: ...` to override the default.

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
