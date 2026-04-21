# rfnry-chat-client

Python client for rfnry/chat. Participate in a chat as an external assistant or a headless user service.

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

    @client.on_tool_call("get_company_policy", in_run=True)
    async def lookup(ctx, send):
        policy = await policy_db.get(ctx.event.tool.arguments["topic"])
        yield send.tool_result(ctx.event.tool.id, result=policy)

    await client.connect()
    await client.join_thread("t_1")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
```

## Handler API

Handlers take `(ctx, send)`. An async function without `yield` is an observer; an async generator that `yield`s events from `send` emits them back to the thread, authored by `self.identity`.

- `@client.on(event_type, *, tool=None, in_run=False, all_events=False)` — base decorator.
- `@client.on_message()`, `@client.on_reasoning()`, `@client.on_tool_result()` — sugar.
- `@client.on_tool_call(name=None)` — sugar; `name=None` matches any tool call.
- `@client.on_any_event()` — wildcard across every event type.

Default filters:
- Self-authored events are skipped (no self-triggering).
- Events with a recipient list that does not include you are skipped.
- Opt out with `all_events=True` for audit / moderation.
- `in_run=True` wraps the handler in a server-tracked `Run` via `run:begin` / `run:end`.

Chain-depth cap (`MAX_HANDLER_CHAIN_DEPTH = 8`) prevents runaway emit chains.

## Streaming

An assistant can stream tokens for a message or reasoning event. Requires the handler be registered with `in_run=True` so the stream has a run_id to attach to.

```python
@client.on_message(in_run=True)
async def reply(ctx, send):
    async with send.message_stream() as stream:
        async for token in my_llm.stream(ctx.event):
            await stream.write(token)
    # on exit: stream:end frame broadcast + a MessageEvent with concatenated
    # text is published as the canonical final event.
```

`send.reasoning_stream()` streams reasoning events the same way. Streaming requires `self.identity` to be an `AssistantIdentity`.

## Testing

Unit tests mock transports. Integration tests spin up a real `rfnry-chat-server` on a dynamically allocated port, backed by the Postgres instance at `DATABASE_URL` (default `postgresql://rfnry_chat:rfnry_chat@localhost:55432/rfnry_chat_test`; start it via the `docker-compose.test.yml` in `packages/server-python`). Integration tests skip automatically if Postgres is unreachable.

## Development

```bash
uv sync --extra dev
uv run poe dev
```
