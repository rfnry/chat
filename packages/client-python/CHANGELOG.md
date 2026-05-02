# Changelog

All notable changes to `rfnry-chat-client` are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `observability/` — `ObservabilityRecord`, `Observability` runtime, 5 sinks (`PrettyStderrSink`, `JsonlStderrSink`, `JsonlFileSink`, `MultiSink`, `NullSink`), `default_observability_sink()` (TTY-aware factory). Always-on; replace sink to redirect.
- `telemetry/` — `TelemetryRow`, `Telemetry.record_run(row)`, 4 sinks (`SqliteTelemetrySink` default, `JsonlTelemetrySink`, `MultiTelemetrySink`, `NullTelemetrySink`). One row per handler-driven Run (events_emitted, tool_calls, tool_errors, duration_ms, error metadata). `ChatClient(data_root=Path(...))` auto-wires `SqliteTelemetrySink`.
- Structured `obs.log(...)` calls at handler-error and reconnect-failure boundaries.

### Schema

- Every persisted record carries `schema_version: int = 1`. Bump on rename/retype/remove. Additive changes do not bump.

## [0.1.0] — 2026-05-01

Inaugural release. Earlier `0.2.x` line was a prototype shape that has been retired; this is the first version intended for production use, on the foundation of the participant-first refactor.

### Added

- `ChatClient` — async client connecting any `Identity` (user, assistant, system) to an `rfnry-chat-server` host.
- Decorator-shaped handler API — `@client.on_message`, `@client.on_reasoning`, `@client.on_tool_call(name)`, `@client.on_tool_result`, `@client.on_any_event`, `@client.on_invited`.
- Typed protocol-frame handlers — `@client.on_thread_updated`, `@client.on_members_updated`, `@client.on_run_updated`, `@client.on_presence_joined`, `@client.on_presence_left`.
- `Send` context manager — `async with client.send(thread_id) as send:` wraps run lifecycle, stamps the right author, closes the run on exit (happy path or exception). Supports `lazy=True` to defer run open until the first emit.
- Proactive openers — `client.send_to(identity)` and `client.open_thread_with(...)` create-or-fetch a thread, optionally invite, join, and send a first message in one call.
- `ChatClientPool` — one connected client per chat-server host, lazily managed, with shared authentication.
- `ChatClient.reconnect(base_url=...)` — runtime URL switch preserving registered listeners.
- Streaming — `send.message_stream()` returns a `Stream` for token-level emission; final `MessageEvent` / `ReasoningEvent` committed on close.
- Loop prevention — handlers never fire on events they themselves authored; `MAX_HANDLER_CHAIN_DEPTH = 8` contextvar backstop.
- Default dispatch filters — self-authored and recipient-mismatched events skipped; opt out per-handler with `all_events=True`.
- `auto_join_on_invite` — `ChatClient(...)` defaults to True; opt out to inspect a `thread:invited` frame before joining.
- Members cache — per-thread member list cached and invalidated on member transitions for hot-path handler resolution.

### Tested

- 209 tests covering handler dispatch, frame parsing, send context manager (eager + lazy), pool lifecycle, reconnect-with-listener-restore, mention routing, and an end-to-end three-agent run-lifecycle smoke test.
