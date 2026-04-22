# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Monorepo with three sibling packages under `packages/`:

- `server-python/` — `rfnry-chat-server`. FastAPI + Socket.IO hub.
- `client-python/` — `rfnry-chat-client`. Backend agents (LLM-driven assistants, webhook monitors) connect through this.
- `client-react/` — `@rfnry/chat-client-react`. Browser client; hooks + `<ChatProvider>` over zustand + TanStack Query.

All three depend on a shared protocol package that lives **outside this repo** at `../../../types/packages/{chat-python,chat-typescript}` (sibling repo `rfnry/types`). The Python packages reference it via `tool.uv.sources` (editable path), and the React package via a `file:` dependency. If `uv sync` or `npm install` fails resolving `rfnry-chat-protocol` / `@rfnry/chat-protocol`, that sibling checkout is missing or out of sync.


## Common commands

Each package is independent — `cd packages/<pkg>` first. There is no top-level orchestrator.

### Python packages (`server-python`, `client-python`)

Both use `uv` + `poethepoet`. Tasks are defined in each `pyproject.toml` under `[tool.poe.tasks]`.

```bash
uv sync --extra dev
uv run poe dev          # check + typecheck + test
uv run poe check        # ruff lint
uv run poe check:fix    # ruff lint --fix
uv run poe format       # ruff format
uv run poe typecheck    # mypy on src/
uv run poe test         # pytest
uv run poe test:cov     # pytest with coverage
uv run poe build        # python -m build
```

Run a single test: `uv run pytest tests/path/to/test_x.py::test_name -x`.

### React package (`client-react`)

```bash
npm install
npm run check           # biome check
npm run check:fix
npm run format          # biome format --write
npm run typecheck       # tsc --noEmit
npm run test            # vitest run
npm run test:watch
npm run build           # tsup → dist/{main.js,main.cjs,main.d.ts}
```

Run a single test: `npx vitest run tests/path/to/file.test.ts -t "name"`.

### Integration tests (server + client-python)

Server integration tests and client-python integration tests need a real Postgres. From `packages/server-python/`:

```bash
docker compose -f docker-compose.test.yml up -d   # postgres on :55432
```

Default DSN: `postgresql://rfnry_chat:rfnry_chat@localhost:55432/rfnry_chat_test` (override via `DATABASE_URL`). client-python integration tests skip automatically if Postgres is unreachable; they spin up a real `rfnry-chat-server` on a dynamically allocated port.

### CI

GitHub workflows under `.github/workflows/` only handle publishing (`publish-server-python.yml`, `publish-client-react.yml`) on tag push — there is no CI that runs the suite, so verify locally.

## Architecture

### The participant-first model (read this first)

**The server is a pure routing hub.** It does not run AI agents, does not own assistant logic, does not auto-invoke anyone. Humans, AI assistants, and system identities are all "participants" with an `Identity` (`UserIdentity` | `AssistantIdentity` | `SystemIdentity`). They all connect via a `ChatClient` — the React one in a browser, the Python one in an agent service.

### Symmetric `(ctx, send)` handler API

`ChatServer` and Python `ChatClient` expose the same decorator pattern:

```python
@server.on("message")                      # observer (no yield)
@server.on_tool_call("get_stock")          # emitter (yields events; auto-wrapped in a Run)
@client.on_message()                       # client side, identical signature
@client.on_invited()                       # proactive: fires when added to a thread
```

`ctx` carries the triggering event + thread; `send` is an event factory whose outputs are stamped with the right author (`SystemIdentity` on the server, `self.identity` on the client). React mirrors this with hooks: `useMessageHandler`, `useToolCallHandler`, `useHandler`, `useInviteHandler`, `useAnyEventHandler`.

### Loop prevention (do not weaken)

Two mechanisms, both intentional:

1. Handlers never fire on events they themselves authored (`author.id == self.identity.id` / `system.id`).
2. `MAX_HANDLER_CHAIN_DEPTH = 8` (contextvar) is a hard backstop against runaway emit chains.

Removing either causes infinite cascades. The matching constant is exported from both `rfnry_chat_server` and `rfnry_chat_client` — keep them in lockstep.

### Tools as events, not as RPC

`tool.call` and `tool.result` are first-class `Event` types correlated by `tool.id`. There is no action registry, no `/actions` endpoint. Anyone in the thread who knows a tool name can publish a `tool.result`; multiple responders are correlated by id. `@server.on_tool_call(name)` is the narrow exception — server-side execution wrapped in a server-owned `Run` authored by `SystemIdentity`.

### Recipients are semantic, not delivery

`event.recipients` is persisted unchanged but **does not filter delivery**. Every member of the thread room receives every event. The SDK dispatch layer applies the filter client-side (skip if `recipients is not None and self.id not in recipients`). To bypass for audit/moderation: `all_events=True` (Python) or `{ allEvents: true }` (React).

### Run = observability envelope (not an executor)

`Run` rows track started/completed/failed/cancelled lifecycle for any unit of work. They do **not** drive execution. Sockets: `run:begin` returns a `run_id`, `run:end` closes it (with optional error). The Python client's emitter handlers wrap this transparently via a contextvar. Granularity is one Run per worker, not per "round" — if a user addresses two assistants, that's two parallel runs.

A watchdog (started via `ChatServer.start()` in a FastAPI lifespan) sweeps stale runs (`status IN ('pending','running') AND started_at < now() - run_timeout_seconds`) and transitions them to `failed(timeout)`. Configure with `run_timeout_seconds` and `watchdog_interval_seconds` on `ChatServer(...)`.

### Inbox rooms (proactive agents)

Every authenticated socket auto-joins a room `inbox:<identity_id>` scoped to its tenant namespace. When `POST /threads/:id/members` adds someone, the server emits a transient `thread:invited` frame to that inbox room. Both clients consume it:

- React: `<ChatProvider>` hydrates the thread, auto-joins, fires `onThreadInvited` / `useInviteHandler`. Opt out with `autoJoinOnInvite={false}`.
- Python: `@client.on_invited()` + `client.open_thread_with(...)`. Opt out with `auto_join_on_invite=False` to `ChatClient(...)`.

Self-adds (creator joining their own new thread) are suppressed.

### Multi-tenancy via namespace_keys

`ChatServer(namespace_keys=[...])` enables a wildcard Socket.IO namespace; each connection's tenant scope is derived from identity metadata via `derive_namespace_path`. Threads + events are scoped per-tenant; enforced at store + broadcast layers. `NamespaceViolation` is the typed error.

### Storage

`ChatStore` is a `Protocol`. Two impls ship: `InMemoryChatStore` (tests, prototyping) and `PostgresChatStore` (production, asyncpg-based; schema in `store/postgres/schema.sql`). Anything new must implement the protocol — don't reach into the postgres class directly.

### Streaming

`stream:start` / `stream:delta` / `stream:end` relay token streams from a participant to the thread room. Streams require a `run_id`. Idiomatic path: an async-generator handler (Run auto-opened) using `send.message_stream()`. Manual path: open the run yourself with `client.begin_run(...)` and pass `run_id=` into the stream factory.

## Conventions worth preserving

- **No backwards-compat shims.** All consumers are owned; breaking changes are taken cleanly. Don't add deprecation wrappers, renamed-var aliases, or "removed" comments.
- **Server-side imports stay one-directional.** `rfnry-chat-server` must not import `rfnry-chat-client`. (The reverse — client dev-deps on server — is allowed for integration tests.)
- **Error type discipline.** Socket failures throw `SocketTransportError(code, message)`; HTTP failures throw `ChatHttpError` (or its subclasses `ThreadNotFoundError`, `ThreadConflictError`, `ChatAuthError`). They are deliberately distinct — don't unify them.
- **React: `biome` enforces single quotes, no semicolons, 2-space indent, line-width 100.** Python: `ruff` enforces line-length 120, double-quoted strings, py3.11 target.
