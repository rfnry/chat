# organization-workspace example

One codebase, two runtime variants. Each workspace runs its own chat-server + its own specialized AI agent on its own port. The React frontend points at whichever workspace the user selects and reconnects when they switch.

- **legal workspace** — `Legal Advisor` agent with `search_case_law` + `draft_clause` tools.
- **medical workspace** — `Medical Reference Assistant` agent with `drug_interaction_check` + `symptom_triage` tools.

Humans drop into a thread; the workspace's agent is already a member; multiple people + one specialized agent collaborate.

## Layout

```
src/
  main.py              FastAPI lifespan — workspace-parametrized
  settings.py          Reads WORKSPACE env var; exposes workspace-derived identity,
                       token, prompt, tools surface
  chat.py              create_chat_server() + observability handler
  agent/
    client.py          create_chat_client() — assistant token per workspace
    assistant.py       (ctx, send) handler; loops with Anthropic + workspace tools
    provider.py        Anthropic SDK glue (identical across workspaces)
  tools.py             Tool definitions keyed by workspace; shared executor
  auth.py              Token-based auth — user tokens + workspace-specific assistant
  db.py                LazyStore + pool factory
```

The only file that cares *which* workspace is `settings.py`. Everything else reads from `settings.*` and does the right thing.

## Run

```bash
# Postgres (shared across workspaces for the demo):
cd ../../../packages/server-python
docker compose -f docker-compose.test.yml up -d

# Anthropic (optional — agent stubs without it):
export ANTHROPIC_API_KEY=sk-ant-...

# Legal workspace — terminal 1:
cd ../../examples/python/organization-workspace
uv sync
WORKSPACE=legal  PORT=8001 uv run uvicorn src.main:asgi --host 0.0.0.0 --port 8001

# Medical workspace — terminal 2:
WORKSPACE=medical PORT=8002 uv run uvicorn src.main:asgi --host 0.0.0.0 --port 8002
```

Two separate FastAPI processes, each with its own ChatServer + agent, on different ports.

## How the React client switches between them

`packages/client-react`'s `ChatProvider` binds to one URL per instance — not designed to swap URLs in place. The idiomatic React pattern is to **re-mount the provider** when the workspace changes. Pass `key={workspace.id}` and React unmounts the old tree (closing the socket via the provider's effect cleanup) before mounting the new one. See `examples/react/organization-workspace/app.tsx`.

## Tenancy note

For demo simplicity, both workspaces share the same Postgres database. Threads created in the legal workspace live in the same `threads` table as medical ones; they're kept apart only by the React side's per-workspace localStorage thread id. In a real multi-tenant deployment you'd use `ChatServer(namespace_keys=["workspace"])` and set `tenant: {workspace: "legal"}` on every thread, which gives hard DB-level isolation via tenant-scoped queries.
