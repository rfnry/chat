# rfnry-chat-client

Python client for rfnry/chat. Any identity role — `UserIdentity`, `AssistantIdentity`, `SystemIdentity` — can connect through this client. The example below uses an `AssistantIdentity` because that's the common case (LLM-driven agents); a headless user service would instantiate a `UserIdentity` and use the same API.

## Install

```bash
pip install rfnry-chat-client
```

## Example

```python
import asyncio

from rfnry_chat_client import ChatClient
from rfnry_chat_protocol import AssistantIdentity, TextPart


async def main() -> None:
    me = AssistantIdentity(
        id="policies-bot",
        name="Policies",
        metadata={"tenant": {"org": "acme"}},
    )

    async def authenticate() -> dict:
        return {
            "headers": {"authorization": "Bearer <service-token>"},
            "auth": {"identity_id": me.id},
        }

    client = ChatClient(
        base_url="http://chat-server.internal",
        identity=me,
        authenticate=authenticate,
    )

    @client.on_message()
    async def handle(ctx, send):
        print(f"[{ctx.event.author.name}] {ctx.event.content}")
        yield send.message(content=[TextPart(text="acknowledged")])

    @client.on_tool_call("get_company_policy")
    async def lookup(ctx, send):
        policy = await policy_db.get(ctx.event.tool.arguments["topic"])
        yield send.tool_result(ctx.event.tool.id, result=policy)

    async def on_connect() -> None:
        await client.join_thread("t_1")

    await client.run(on_connect=on_connect)


if __name__ == "__main__":
    asyncio.run(main())
```

`ChatClient.run()` handles the common long-lived-agent lifecycle: retry the initial connect with backoff, invoke an optional `on_connect` hook (the idiomatic place to join threads / subscribe), hold the task open, and disconnect cleanly on cancellation. If you need lower-level control, call `connect()` / `disconnect()` yourself.

## Handler API

Handlers take `(ctx, send)`. Two shapes:

- **Observer** — a plain async function with no `yield`. Reacts to events, emits nothing, no server round trip for run tracking.
- **Emitter** — an async generator that yields events built from `send.message(...)` / `send.tool_call(...)` / etc. The dispatcher auto-wraps the invocation in a server-tracked `Run` (`run:begin` before, `run:end` after, `run.failed(error)` on exception). Emitted events are stamped with the run id and authored by `self.identity`.

Registration:

- `@client.on(event_type, *, tool=None, all_events=False)` — base.
- `@client.on_message()`, `@client.on_reasoning()`, `@client.on_tool_result()` — sugar.
- `@client.on_tool_call(name=None)` — sugar; `name=None` matches any tool call.
- `@client.on_any_event()` — wildcard across every event type.
- `@client.on_invited()` — fires when this identity is added to a thread. Receives a `ThreadInvitedFrame(thread, added_member, added_by)`. By default, the client auto-joins the thread room before the handler runs, so the handler may assume live event delivery. Pass `auto_join_on_invite=False` to `ChatClient(...)` to opt out.

Server broadcast frames (transient, not persisted events) are also surfaced via decorators — symmetric with how the React provider consumes them:

- `@client.on_thread_updated()` — handler takes `(thread: Thread)`. Fires on thread metadata / tenant changes.
- `@client.on_members_updated()` — handler takes `(thread_id: str, members: list[Identity])`. Fires after any add/remove of thread members, with the full current snapshot.
- `@client.on_run_updated()` — handler takes `(run: Run)`. Fires on run lifecycle transitions (started, completed, failed, cancelled).

Default filters (skipped for `all_events=True`):
- Self-authored events are not dispatched (no self-triggering).
- Events with a recipient list that does not include you are skipped.

Chain-depth cap (`MAX_HANDLER_CHAIN_DEPTH = 8`) prevents runaway emit chains.

## Streaming

An assistant streams tokens for a message or reasoning event. Because streams require a run id, the idiomatic path is an async-generator handler (auto-wrapped in a run). If you need to stream from a plain coroutine handler, open the run manually and pass its id to `send.*_stream(run_id=...)`.

```python
# Idiomatic: generator handler, Run is auto-opened.
@client.on_message()
async def reply(ctx, send):
    async with send.message_stream() as stream:
        async for token in my_llm.stream(ctx.event):
            await stream.write(token)
    if False:  # keep handler a generator; no actual yield needed
        yield  # pragma: no cover

# Manual: coroutine handler opens its own run. begin_run returns the
# run_id directly; call client.get_run(run_id) if you need the full Run.
@client.on_message()
async def reply(ctx, send):
    run_id = await client.begin_run(ctx.event.thread_id, triggered_by_event_id=ctx.event.id)
    try:
        async with send.message_stream(run_id=run_id) as stream:
            async for token in my_llm.stream(ctx.event):
                await stream.write(token)
    finally:
        await client.end_run(run_id)
```

`begin_run` returns the `run_id` as a string (saving an HTTP round-trip). If you need the hydrated `Run` object — e.g. for status reporting — call `await client.get_run(run_id)` explicitly.

Streaming is available to any connected identity (users, assistants, system).

## Proactive flows

Two helpers for agents that initiate conversations (webhook-triggered pings, cron-driven alerts, etc.):

```python
# Open (or reuse) a thread, optionally invite a participant, join, send a message — in one call.
thread, event = await client.open_thread_with(
    message=[TextPart(text="Disk usage on api-03 crossed 90%.")],
    invite=UserIdentity(id="u_alice", name="Alice"), # optional
    thread_id=existing_thread_id_or_None,            # optional; creates if None
    tenant={"org": "acme"},                          # optional
)

# Switch the URL (or auth) at runtime without losing registered handlers.
await client.reconnect(base_url="http://chat-other.internal")
```

For agents that need to talk to many chat servers from one process, `ChatClientPool` keeps one `ChatClient` per URL:

```python
from rfnry_chat_client import ChatClientPool

pool = ChatClientPool(factory=build_client)
client = await pool.get_or_connect("http://chat-a.internal")
# ... use client ...
await pool.close_all()  # or await pool.close("http://chat-a.internal")
```

See `examples/python/monitoring-assistant/` for the canonical webhook-driven shape.

## Error handling

Socket failures raise `SocketTransportError(code, message)`. HTTP failures
raise `ChatHttpError` — or one of its subclasses, depending on the response:
`ThreadNotFoundError`, `ThreadConflictError`, `ChatAuthError`. They are
deliberately distinct; catch them separately.

```python
from rfnry_chat_client import (
    ChatAuthError,
    ChatHttpError,
    SocketTransportError,
    ThreadConflictError,
    ThreadNotFoundError,
)

try:
    await client.rest.get_thread("th_missing")
except ThreadNotFoundError:
    ...
except ChatAuthError:
    ...
except ChatHttpError as e:
    # catch-all for any other HTTP failure
    print(e.status, e.body)

try:
    await client.socket.send_message(thread_id, draft)
except SocketTransportError as e:
    print(e.code, e.message)
```

## Testing

Unit tests mock transports. Integration tests spin up a real `rfnry-chat-server` on a dynamically allocated port, backed by the Postgres instance at `DATABASE_URL` (default `postgresql://rfnry_chat:rfnry_chat@localhost:55432/rfnry_chat_test`; start it via the `docker-compose.test.yml` in `packages/server-python`). Integration tests skip automatically if Postgres is unreachable.

## Development

```bash
uv sync --extra dev
uv run poe dev
```
