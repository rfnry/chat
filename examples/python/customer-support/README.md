# customer-support example

Two architecturally independent pieces run inside one FastAPI process:

1. **Chat server** (`chat.py`) — holds threads, members, events, runs. Logs every message it sees.
2. **Agent** (`agent/`) — an `AssistantIdentity` that connects to the server as an external participant using `rfnry-chat-client`. Forwards each user message to Anthropic (if `ANTHROPIC_API_KEY` is set) and emits the reply back into the thread.

They share a FastAPI process for convenience. In production you'd split them into two services; the architecture is already decoupled.

## Layout

```
src/
  main.py              FastAPI app + lifespan — InMemoryChatStore, schedules the agent
  chat.py              ChatServer + a simple message logger
  agent/
    client.py          ChatClient lifecycle — connect, retry, register the assistant handler
    assistant.py       (ctx, send) handler: history → model call → message back
    provider.py        Anthropic SDK glue (model id, max tokens, message conversion)
```

The three-file `agent/` split is intentional:

- **`provider.py`** is the *only* file that imports `anthropic`. Swap it for a different LLM without touching anything else.
- **`assistant.py`** is the business logic — build messages, call the model, emit the response.
- **`client.py`** is transport — it builds a `ChatClient`, retries the connection, and registers the handler.

Storage is `InMemoryChatStore` (in-process dicts). Auth is off — the client sends its identity via the `x-rfnry-identity` header (auto-encoded when a `ChatClient` is built with no `authenticate` callback).

## Run

```bash
# Optional — stubs if missing:
export ANTHROPIC_API_KEY=sk-ant-...

cd examples/python/customer-support
uv sync
uv run uvicorn src.main:asgi --host 0.0.0.0 --port 8000
```

The agent auto-connects after startup. No database, no auth, no external services.
