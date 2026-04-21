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

## Tenant data flow

Each user's identity carries both tenant scope (organization, workspace) and role. The React client sends these via the Socket.IO handshake's `auth` payload; the Python `authenticate` callback writes them into `Identity.metadata`; the agent reads them off `ctx.event.author.metadata` when handling a message.

```
React                Server auth             Identity.metadata
---                  ---                     ---
auth: {              authenticate(handshake) {tenant: {organization: "acme_corp",
  token: "u_alice",  → writes                          workspace: "legal"},
  organization,                              role: "manager"}
  role,
}
```

The agent uses this in two ways that this example demonstrates:

### Medical workspace — role-based gating

`src/agent/policy.py::gate_reply` denies AI access when the requester's role isn't `manager`. The check runs as the first step of the agent's `@client.on_message` handler. Members can still join the thread and chat with other humans — the agent just replies with a short denial (addressed to the member only) and skips the Anthropic call.

```python
def gate_reply(author: Identity) -> str | None:
    if settings.WORKSPACE != "medical":
        return None
    if author.metadata.get("role") != "manager":
        return (
            f"Only managers can request clinical references from me. "
            f"{author.name}, your current role is {role!r}."
        )
    return None
```

### Legal workspace — requester context in the system prompt

`src/agent/policy.py::author_context` formats the requester's tenant data and appends it to the Anthropic system prompt. Claude then knows who's asking and can cite them by name when drafting clauses or summarizing cases.

```python
system_prompt = f"{settings.SYSTEM_PROMPT}\n\n{author_context(author)}"
# → "The current requester is U Alice (id=u_alice, role=manager)
#    from organization=acme_corp in the legal workspace. When a drafted
#    clause or case lookup is specific to them, reference them by name."
```

Both behaviors are in `policy.py` as plain functions keyed off `settings.WORKSPACE`. Swap out the implementations per workspace without touching the dispatcher or the SDK.

## How the React client switches between them

`packages/client-react`'s `ChatProvider` binds to one URL and one auth callback per instance — not designed to swap them in place. The idiomatic React pattern is to **re-mount the provider** when the workspace or role changes. Use a composite key:

```tsx
<ChatProvider
  key={`${workspace.id}:${role}`}
  url={workspace.url}
  authenticate={async () => ({
    headers: { authorization: `Bearer ${userToken}` },
    auth: { organization, role },
  })}
>
```

When the key changes, React unmounts the old tree (calling `client.disconnect()` via the provider's effect cleanup) before mounting the new one with the new URL and/or new auth payload.

## Tenancy note

For demo simplicity, both workspaces share the same Postgres database. Threads created in the legal workspace live in the same `threads` table as medical ones; they're kept apart only by the React side's per-workspace `localStorage` thread id. In a real multi-tenant deployment you'd use `ChatServer(namespace_keys=["workspace"])` and set `tenant: {workspace: "legal"}` on every thread, which gives hard DB-level isolation via tenant-scoped queries.
