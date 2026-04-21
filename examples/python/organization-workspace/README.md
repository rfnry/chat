# organization-workspace example

One codebase, two runtime variants. Each workspace runs its own chat-server + its own specialized AI agent on its own port. The React frontend points at whichever workspace the user selects and reconnects when they switch.

- **legal workspace** — `Legal Advisor` agent. Prepends the requester's tenant metadata to the system prompt.
- **medical workspace** — `Medical Reference Assistant`. Replies only when the requester's `role == "manager"`; members get a short denial.

Humans drop into a thread; the workspace's agent is already a member; multiple people + one specialized agent collaborate.

## Layout

```
src/
  main.py              FastAPI lifespan — reads WORKSPACE env var, dispatches to the right agent
  chat.py              create_chat_server() + a simple message logger
  agent_legal/
    client.py          create_chat_client() — metadata.tenant.workspace = "legal"
    assistant.py       (ctx, send) handler; appends requester context to the system prompt
    provider.py        Anthropic SDK glue
  agent_medical/
    client.py          create_chat_client() — metadata.tenant.workspace = "medical"
    assistant.py       (ctx, send) handler; gates replies to role=="manager"
    provider.py        Anthropic SDK glue
```

Each workspace has its own agent module — no shared policy, no workspace conditionals. Duplication is intentional: each agent is trivially readable end-to-end.

Storage is `InMemoryChatStore` (in-process dicts). Auth is off — the server extracts the identity from the handshake or the `x-rfnry-identity` header and trusts it. Fine for demos; absolutely not for production.

## Run

```bash
# Anthropic (optional — agent stubs without it):
export ANTHROPIC_API_KEY=sk-ant-...

# Legal workspace — terminal 1:
cd examples/python/organization-workspace
uv sync
WORKSPACE=legal  PORT=8001 uv run uvicorn src.main:asgi --host 0.0.0.0 --port 8001

# Medical workspace — terminal 2:
WORKSPACE=medical PORT=8002 uv run uvicorn src.main:asgi --host 0.0.0.0 --port 8002
```

Two separate FastAPI processes, each with its own ChatServer + agent, on different ports. No database, no auth, no external services.

## Tenant data flow

Each user's identity carries both tenant scope (organization, workspace) and role. The React client passes them on `ChatProvider`'s `identity` prop; the server's default authenticator parses the handshake's `x-rfnry-identity` header and produces the `Identity`; the agent reads `ctx.event.author.metadata` when handling a message.

```
React <ChatProvider identity={...}>    →    x-rfnry-identity header    →    Identity.metadata
```

The two agents demonstrate two different uses of this data:

### Medical workspace — role-based gating

`src/agent_medical/assistant.py` inspects `author.metadata["role"]` as the first step of the handler. Members can still join the thread and chat with other humans — the agent just replies with a short denial (addressed to the member only) and skips the Anthropic call.

```python
role = (author.metadata or {}).get("role")
if role != "manager":
    yield send.message(
        content=[TextPart(text=f"Only managers can request clinical references from me. "
                                f"{author.name}, your current role is {role!r}.")],
        recipients=[author.id],
    )
    return
```

### Legal workspace — requester context in the system prompt

`src/agent_legal/assistant.py` formats the requester's tenant data and appends it to the Anthropic system prompt. Claude then knows who's asking and can cite them by name.

```python
system_prompt = f"{SYSTEM_PROMPT}\n\n{_requester_context(author)}"
# → "The current requester is Alice (id=u_alice, role=manager)
#    from organization=acme_corp in the legal workspace. Reference them by name when appropriate."
```

## How the React client switches between them

`packages/client-react`'s `ChatProvider` binds to one URL and one identity per instance. The idiomatic React pattern is to **re-mount the provider** when the workspace or role changes. Use a composite key:

```tsx
<ChatProvider
  key={`${workspace.id}:${role}`}
  url={workspace.url}
  identity={{
    id: 'u_alice',
    role: 'user',
    name: 'Alice',
    metadata: { role, tenant: { organization, workspace: workspace.id } },
  }}
>
```

When the key changes, React unmounts the old tree (calling `client.disconnect()` via the provider's effect cleanup) before mounting the new one with the new URL and new identity metadata.
