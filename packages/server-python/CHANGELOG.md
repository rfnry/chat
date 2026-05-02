# Changelog

All notable changes to `rfnry-chat-server` are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `observability/` — `ObservabilityRecord`, `Observability` runtime, 5 sinks (`PrettyStderrSink`, `JsonlStderrSink`, `JsonlFileSink`, `MultiSink`, `NullSink`), `default_observability_sink()` (TTY-aware factory). Always-on; replace sink to redirect.
- `telemetry/` — `TelemetryRow`, `Telemetry.record_run(row)`, 4 sinks (`SqliteTelemetrySink` default, `JsonlTelemetrySink`, `MultiTelemetrySink`, `NullTelemetrySink`). One row per `Run` written at `end_run`. `ChatServer(data_root=Path(...))` auto-wires `SqliteTelemetrySink`.
- Structured `obs.log(...)` calls at run/stream/invite boundaries and at silent-swallow sites (watchdog, handler dispatcher, members cache, transport).

### Schema

- Every persisted record carries `schema_version: int = 1`. Bump on rename/retype/remove. Additive changes do not bump.

## [0.1.0] — 2026-05-01

Inaugural release. Earlier `0.2.x` line was a prototype shape that has been retired; this is the first version intended for production use, on the foundation of the participant-first refactor.

### Added

- `ChatServer` — FastAPI + Socket.IO chat hub with REST routes for threads, members, events, and runs, plus a Socket.IO namespace for real-time delivery.
- Symmetric participation model — humans, AI assistants, and system identities all map to `Identity` rows and share the same socket protocol.
- Tools as events — `tool.call` / `tool.result` are first-class events correlated by tool id; multiple responders supported.
- Streaming — `stream:start` / `stream:delta` / `stream:end` relay token streams owned by a `Run`.
- Run lifecycle — `pending → running → completed | failed | cancelled`, with a configurable watchdog that reaps stale runs (`run_timeout_seconds`, `watchdog_interval_seconds`).
- Inbox rooms — every authenticated socket auto-joins a per-identity inbox room; adding a member to a thread emits a transient `thread:invited` frame.
- Multi-tenancy — `namespace_keys` carve up the Socket.IO namespace per tenant; threads/events/broadcasts isolated at store + transport layers; `NamespaceViolation` typed for handler-level rejection.
- Authentication / authorization — `AuthenticateCallback` resolves identity at handshake; `AuthorizeCallback` gates membership and event emission.
- Pluggable storage — `ChatStore` Protocol; ships `InMemoryChatStore` (tests, prototyping) and `PostgresChatStore` (production, asyncpg-based, schema in `store/postgres/schema.sql`).
- Pluggable broadcast — `Broadcaster` Protocol; ships `SocketIOBroadcaster` (default) and `RecordingBroadcaster` (tests).
- Server-side handler API — `@server.on("event_type")` for observers, `@server.on_tool_call(name)` for emitters wrapped in a server-owned `Run`.
- Loop prevention — `MAX_HANDLER_CHAIN_DEPTH = 8` contextvar backstop; handlers never fire on events they themselves authored.
- Mention routing — `@<identity_id>` in message prose resolves into `recipients` when the sender hasn't set the field explicitly.
- Analytics hooks — `AnalyticsEvent` / `AssistantAnalytics` for plumbing observability into your own pipeline.

### Tested

- 345 tests including integration against real Postgres + Socket.IO, presence races, tenant namespace dispatch, mention routing, run lifecycle E2E.
