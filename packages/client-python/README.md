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

    @client.on_message
    async def handle(event):
        print(f"[{event.author.name}] {event.content}")

    @client.on_tool_call("get_company_policy")
    async def lookup(event):
        ...

    await client.connect()
    await client.join_thread("t_1")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
```

## Scope (Phase A)

This release ships the transport and dispatch surface that works against the current server:

- Connect to a chat server as any `Identity` (assistant, user, or system).
- Join and leave threads, receive every event type, send text and content messages.
- Dispatch to per-event-type handlers with sensible filtering defaults:
  - Self-authored events are skipped.
  - Events with a recipient list that does not include you are skipped.
  - Opt out per handler with `all_events=True` for audit or moderation roles.

## Coming in Phase B (requires server refactor)

- Emitting `tool.call`, `tool.result`, and `reasoning` events from the client.
- Run lifecycle wrapping (`run:begin` and `run:end`) for observability.
- Streaming emission from the client.

## Development

```bash
uv sync --extra dev
uv run poe dev
```
