# rfnry-chat-client

Python client for rfnry/chat — for backend services that want to *be* a participant. Whether you're an LLM-driven assistant, a webhook-triggered monitor, or a headless user agent, you connect once with an identity and behave like any other member of a thread. Decorator-driven handler API, run lifecycle wrapped for you, proactive flow built in.

This is the SDK you reach for when you want to ship an AI that talks to people in real time without rebuilding the chat layer. Compared to agent frameworks where the chat surface is an afterthought (request/response over HTTP, tools bolted on top), this client treats the chat thread as the runtime: messages and tool calls are events you observe, runs are lifecycles you participate in, and your agent can initiate as freely as it can react.

## Getting Started

```bash
pip install rfnry-chat-client
```

```python
import asyncio
from rfnry_chat_client import ChatClient
from rfnry_chat_protocol import AssistantIdentity, TextPart

async def main() -> None:
    me = AssistantIdentity(id="policies-bot", name="Policies", metadata={})

    async def authenticate() -> dict:
        return {"headers": {"authorization": "Bearer <service-token>"}}

    client = ChatClient(base_url="http://chat.internal", identity=me, authenticate=authenticate)

    @client.on_message()
    async def reply(ctx, send):
        async with send.message() as out:
            out.append(TextPart(text=f"got: {ctx.event.text}"))

    async with client.running():
        await asyncio.Event().wait()

asyncio.run(main())
```

`@client.on_message()`, `@client.on_tool_call(name)`, `@client.on_invited()` and friends do the registration. `send` is a context manager that opens a Run, stamps the right author, and closes the Run when the block exits — happy path or exception.

## Features

**Decorator-shaped handler API.** `@on_message`, `@on_reasoning`, `@on_tool_call(name)`, `@on_tool_result`, `@on_any_event`, `@on_invited`, plus the typed protocol-frame handlers (`@on_thread_updated`, `@on_run_updated`, `@on_presence_joined`, etc.). Each handler receives a `ctx` (triggering event + thread + thread-scoped state) and a `send` (an emitter that knows your identity, the active run, and how to stamp events). Self-authored events and recipient-mismatched events are filtered by default; opt out with `all_events=True` when you genuinely need the firehose.

**Proactive openers.** `client.send_to(identity)` and `client.open_thread_with(...)` create a thread (or reuse one), invite a user, join, and send a first message in one call. Combined with the inbox rooms on the server, this lets an agent reach a user who isn't in any thread yet — the user's browser receives a `thread:invited` frame, hydrates the thread, and renders. The webhook/cron/event-bus → user-notification pattern collapses to four lines.

**Run lifecycle handled for you.** Emitter handlers (`@on_tool_call(name)`) are wrapped in a server-acknowledged `Run` automatically. The watchdog on the server side reaps stalls so your UI never hangs on a process that died. Need finer control? `client.send(thread_id)` is a context manager you can drive manually; pass `lazy=True` to defer the Run open until the first emit.

**Streaming.** `send.message_stream()` returns a `Stream` you write tokens into; `stream:start` / `stream:delta` / `stream:end` frames relay them to the thread room. The final `MessageEvent` (or `ReasoningEvent`) is committed when the stream closes. Idiomatic path is the async-generator handler — yield events from the generator and the dispatcher wraps the Run for you.

**Multi-server agents via `ChatClientPool`.** One agent process can serve many chat servers — `ChatClientPool` holds one connected client per host, lazily, with shared authentication. `ChatClient.reconnect(base_url=...)` switches URLs at runtime if you ever need to rebind a single connection.

**Loop prevention built in.** Handlers never fire on events they themselves authored, and `MAX_HANDLER_CHAIN_DEPTH = 8` is a hard backstop against runaway emit chains. Both are intentional and load-bearing — removing either causes infinite cascades when two agents talk to each other.

## License

MIT — see [`LICENSE`](./LICENSE).
