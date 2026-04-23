# team-communication: Slack-shape example + presence primitive

**Date:** 2026-04-23
**Status:** Design — approved, awaiting implementation plan
**Touches:** `rfnry/types` (protocol), `rfnry/chat` (server, client-python, client-react), `rfnry/yard` (new example)

## Problem

`rfnry-chat` ships with two reference examples that prove out distinct access patterns:

- `stock-assistant` — single agent, membership-based, alert webhook opens DMs.
- `multi-tenant` — workspace-as-room via tenant matching, agents auto-join all tenant-visible threads.

Neither demonstrates a Slack-shaped product where **users and agents share one workspace**, communicating asynchronously through public channels and private DMs, with live "who's online" awareness. Building that example exposes a missing primitive in the library: **presence**. The chat server already tracks Socket.IO connect/disconnect lifecycle and has clean room primitives (`thread:<id>`, `inbox:<id>`, `tenant:<path>`), but exposes no first-class concept of "this identity is currently connected." Every consumer who needs a member directory has to invent their own polling/REST endpoint.

This design adds presence as a library primitive and uses it to ship a new example, `team-communication`, that demonstrates the full Slack shape.

## Goals

1. Add a typed presence primitive to `rfnry-chat` (protocol + server + Python client + React client) that broadcasts identity online/offline status over Socket.IO.
2. Build `team-communication` — a Slack-like demo with channels, DMs, multiple users in different tabs, and three independently-running AI agents.
3. Demonstrate proactive agent messaging triggered from the client UI, where the agent uses Anthropic to compose a real message in real time (streamed) about a mocked subject.
4. Demonstrate `multi-tenant`'s tenant-room access pattern and `stock-assistant`'s membership pattern composed in **one** server's `authorize` callback.

## Non-goals

- Persistence beyond `InMemoryChatStore`. Presence is in-memory by design — server restart resets it (correct semantics).
- Reconnect debouncing on `presence:left`. First cut fires immediately on the last socket dropping; debouncing is a follow-up if reconnect noise becomes a problem.
- Typing indicators, read receipts, threading, reactions, or any other Slack feature beyond channels + DMs + presence + ping.
- Mention as a first-class protocol type. The library already exposes `parseMemberMentions` (text scan for `@name`); we keep that contract.
- Multi-tenancy / `namespace_keys` in the example itself. The presence implementation in the library must work correctly under both modes; the example uses single-scope mode.

## Approved decisions (from brainstorming)

1. **Presence semantics:** per-identity refcount. `presence:joined` fires only on the 0→1 transition (first socket); `presence:left` fires only on 1→0 (last socket disconnects). Multi-tab and reconnect are silent.
2. **Channels vs DMs:** hybrid — channels via tenant rooms, DMs via membership. Both models composed in one `authorize` callback.
3. **Initial sync:** REST snapshot via `GET /chat/presence`. Live deltas patched on top via `presence:joined` / `presence:left` frames.
4. **Ping UX:** top-of-panel control, fully decoupled from the open thread. Agent select + channel select + two buttons ("Ping in channel", "Ping me direct"). Always visible, regardless of what's open.
5. **Ping content:** Anthropic-generated, streamed. Each agent has a persona prompt and a small subject pool; the LLM composes the actual message in character. Stub fallback (no API key) sends a one-shot placeholder.

---

## Architecture

### Layer 1 — Protocol (`rfnry/types`)

Two new modules — `presence.py` and `presence.ts` — added under each protocol package and re-exported from the barrel.

**Python (`types/packages/chat-python/src/rfnry_chat_protocol/presence.py`):**

```python
from datetime import datetime
from pydantic import BaseModel
from .identity import Identity

class PresenceSnapshot(BaseModel):
    members: list[Identity]

class PresenceJoinedFrame(BaseModel):
    identity: Identity
    at: datetime

class PresenceLeftFrame(BaseModel):
    identity: Identity
    at: datetime
```

**TypeScript (`types/packages/chat-typescript/src/presence.ts`):**

```typescript
import type { Identity, IdentityWire } from './identity'

export type PresenceSnapshot = { members: Identity[] }
export type PresenceJoinedFrame = { identity: Identity; at: string }
export type PresenceLeftFrame  = { identity: Identity; at: string }

export type PresenceSnapshotWire = { members: IdentityWire[] }
export type PresenceJoinedFrameWire = { identity: IdentityWire; at: string }
export type PresenceLeftFrameWire  = { identity: IdentityWire; at: string }

export function parsePresenceJoinedFrame(raw: unknown): PresenceJoinedFrame { ... }
export function parsePresenceLeftFrame(raw: unknown): PresenceLeftFrame { ... }
export function parsePresenceSnapshot(raw: unknown): PresenceSnapshot { ... }
```

Re-exported from `main.ts` / `__init__.py`.

### Layer 2 — Server (`rfnry/chat/packages/server-python`)

**`broadcast/socketio.py`** adds:

```python
def _presence_room(tenant_path: str) -> str:
    return f"presence:{tenant_path}"

class SocketIOBroadcaster:
    async def broadcast_presence_joined(
        self, frame: PresenceJoinedFrame, *, tenant_path: str, namespace: str | None = None
    ) -> None:
        await self._sio.emit(
            "presence:joined",
            frame.model_dump(mode="json", by_alias=True),
            room=_presence_room(tenant_path),
            skip_sid=...,  # do NOT echo to the joining identity's own sockets
            namespace=namespace or "/",
        )

    async def broadcast_presence_left(
        self, frame: PresenceLeftFrame, *, tenant_path: str, namespace: str | None = None
    ) -> None: ...
```

**`socketio/server.py — on_connect`** gains the presence-room join and refcount update:

```python
# after entering inbox: and tenant: rooms
presence_room = _presence_room(_tenant_path(identity_tenant, namespace_keys=ns_keys))
await self.enter_room(sid, presence_room)

is_first_socket = self._server.presence.add(identity.id, sid, identity)
if is_first_socket:
    await self._server.broadcaster.broadcast_presence_joined(
        PresenceJoinedFrame(identity=identity, at=datetime.now(UTC)),
        tenant_path=_tenant_path(...),
        namespace=concrete_ns,
    )
```

**`socketio/server.py — on_disconnect`** mirrors:

```python
async def on_disconnect(self, sid: str, *_args: Any) -> None:
    session = await self.get_session(sid)
    identity: Identity | None = session.get("identity")
    if identity is None:
        return
    is_last_socket = self._server.presence.remove(identity.id, sid)
    if is_last_socket:
        await self._server.broadcaster.broadcast_presence_left(
            PresenceLeftFrame(identity=identity, at=datetime.now(UTC)),
            tenant_path=...,
            namespace=...,
        )
```

**`server/chat_server.py`** owns a small `_PresenceRegistry`:

```python
class _PresenceRegistry:
    def __init__(self) -> None:
        self._sids: dict[str, set[str]] = {}              # identity_id -> sids
        self._identities: dict[str, Identity] = {}        # identity_id -> Identity
        self._tenant_paths: dict[str, str] = {}           # identity_id -> tenant_path
        self._lock = asyncio.Lock()

    async def add(self, identity_id: str, sid: str, identity: Identity, tenant_path: str) -> bool:
        async with self._lock:
            sids = self._sids.setdefault(identity_id, set())
            was_empty = not sids
            sids.add(sid)
            self._identities[identity_id] = identity
            self._tenant_paths[identity_id] = tenant_path
            return was_empty

    async def remove(self, identity_id: str, sid: str) -> tuple[bool, Identity | None, str | None]:
        async with self._lock:
            sids = self._sids.get(identity_id)
            if not sids:
                return False, None, None
            sids.discard(sid)
            if sids:
                return False, None, None
            del self._sids[identity_id]
            ident = self._identities.pop(identity_id, None)
            tp   = self._tenant_paths.pop(identity_id, None)
            return True, ident, tp

    async def list_for_tenant(self, tenant_path: str) -> list[Identity]:
        async with self._lock:
            return [
                self._identities[iid]
                for iid, tp in self._tenant_paths.items()
                if tp == tenant_path
            ]
```

`ChatServer.__init__` constructs one. `ChatServer.start()` is unchanged (no background work needed; presence is purely event-driven).

**`server/rest/presence.py`** — new FastAPI router mounted at `GET /presence`:

```python
@router.get("/presence", response_model=PresenceSnapshot)
async def get_presence(deps: PresenceDeps = Depends(...)) -> PresenceSnapshot:
    members = await deps.server.presence.list_for_tenant(deps.tenant_path)
    return PresenceSnapshot(members=members)
```

Tenant scoping uses the same `_check_namespace_match` rule as `list_threads`. Snapshot excludes the caller themselves (matches the broadcaster's `skip_sid` rule — the caller knows they're online).

### Layer 3 — Python client (`rfnry/chat/packages/client-python`)

**`dispatch.py`** — register two new frame dispatchers, parallel to `_dispatch_thread_invited`:

```python
@self._sio.on("presence:joined", namespace=ns)
async def on_presence_joined(payload):
    frame = PresenceJoinedFrame.model_validate(payload)
    for handler in self._client._presence_joined_handlers:
        await handler(frame)

@self._sio.on("presence:left", namespace=ns)
async def on_presence_left(payload): ...
```

**`client.py`** — public decorators + REST helper:

```python
def on_presence_joined(self):
    def decorator(fn): self._presence_joined_handlers.append(fn); return fn
    return decorator

def on_presence_left(self):
    def decorator(fn): self._presence_left_handlers.append(fn); return fn
    return decorator
```

**`transport/rest.py`** — `await client.rest.list_presence() -> PresenceSnapshot`.

### Layer 4 — React client (`rfnry/chat/packages/client-react`)

**`store/presence.ts`** — small zustand slice:

```typescript
type PresenceState = {
  members: Map<string, Identity>
  hydrated: boolean
}
```

**`provider/ChatProvider.tsx`** — on connect, calls `rest.listPresence()` and seeds the slice; subscribes to `presence:joined` / `presence:left` via `socket.on(...)` and patches the slice.

**`hooks/usePresence.ts`**:

```typescript
export function usePresence(): {
  members: Identity[]
  byRole: { user: Identity[]; assistant: Identity[]; system: Identity[] }
  isHydrated: boolean
}
```

Re-exported from `main.ts`.

---

## Layer 5 — Example: `team-communication`

```
yard/examples/rfnry-chat/team-communication/
├── README.md
├── server-python/        FastAPI + ChatServer with channels + hybrid authorize
├── client-python-a/      Agent A — Eng Manager     (port 9100)
├── client-python-b/      Agent B — Release Coord   (port 9101)
├── client-python-c/      Agent C — Support Liaison (port 9102)
└── client-react/         Frontend (port 5173)
```

### Server

`server-python/src/chat.py`:

```python
CHANNELS = [
    ("ch_general",     "general",     "General team chat"),
    ("ch_engineering", "engineering", "Engineering"),
]

async def _authorize(identity, thread_id, action, *, target_id=None):
    thread = await store.get_thread(thread_id)
    if thread is None:
        return False
    if (thread.metadata or {}).get("kind") == "channel":
        return True
    return await store.is_member(thread_id, identity.id)

async def _bootstrap_channels(store):
    for cid, slug, label in CHANNELS:
        if await store.get_thread(cid) is None:
            await store.create_thread(Thread(
                id=cid,
                tenant={"channel": slug},
                metadata={"kind": "channel", "label": label},
                ...
            ))
```

`server-python/src/main.py` adds a custom `GET /chat/threads` wrapper that filters DMs the caller isn't a member of (channels pass through unchanged). This keeps the library general — the access twist lives in the example.

### Agents (3 × `client-python-{a,b,c}`)

Scaffolding cloned from `stock-assistant/client-python`. Per-agent diffs:

| Agent | id | Port | Persona | Subject pool theme |
|-------|----|----|---------|-------------------|
| A | `agent-a` | 9100 | Eng Manager — direct, terse, code-aware | PRs, builds, reviews |
| B | `agent-b` | 9101 | Release Coordinator — process-y, calendar-aware | Cuts, freezes, rollouts |
| C | `agent-c` | 9102 | Support Liaison — empathetic, customer-voiced | Reported bugs, SLAs |

Each carries `metadata.tenant = {channel: "*"}` and joins every channel thread on connect (same discovery loop as `multi-tenant`). DMs are joined reactively via `@client.on_invited()`.

**Two webhooks per agent**:

```python
@app.post("/ping-channel")
async def ping_channel(body: PingChannelBody):
    subject = random.choice(SUBJECTS)
    await _stream_proactive_message(
        thread_id=body.channel_id,
        subject=subject,
        audience="channel",
        addressee=body.requested_by,
    )

@app.post("/ping-direct")
async def ping_direct(body: PingDirectBody):
    user = UserIdentity(id=body.user_id, name=body.user_name)
    dm_id = _dm_thread_id(client.identity.id, user.id)
    thread, _ = await client.open_thread_with(
        message=None,                       # we'll stream the body separately
        invite=user,
        thread_id=dm_id,
        metadata={"kind": "dm"},
    )
    subject = random.choice(SUBJECTS)
    await _stream_proactive_message(
        thread_id=thread.id,
        subject=subject,
        audience="direct DM",
        addressee=body.requested_by,
    )
```

**Streaming helper** (`_stream_proactive_message`) — opens a `Run` manually, drives `send.message_stream()` from the Anthropic streaming response, finalizes, ends the run. Stub fallback when no API key: one-shot `client.send_message(...)` with `[stub Agent X] subject: <subject>`.

```python
def _dm_thread_id(a: str, b: str) -> str:
    return "dm_" + "__".join(sorted([a, b]))
```

### React client

**Identity** — each tab gets a `Guest-NNNN` user with `tenant.channel = "*"`, persisted to `sessionStorage` (same pattern as `multi-tenant`).

**Layout**:

```
┌─────────────┬───────────────────────────────────────┐
│  Sidebar    │  TopControl  (always visible)         │
│             ├───────────────────────────────────────┤
│  Channels   │  ThreadPanel (channel OR dm OR none)  │
│   #general  │                                       │
│   #engin... │                                       │
│  Users      │                                       │
│   • Alice   │                                       │
│   • Bob     │                                       │
│  Assistants │                                       │
│   • Agent A │                                       │
│   • Agent B │                                       │
│   • Agent C │                                       │
└─────────────┴───────────────────────────────────────┘
```

**Sidebar** (`sidebar.tsx`):

- **Channels** section: `useThreads()` filtered to `metadata.kind === 'channel'`.
- **Users** section: `usePresence().byRole.user`, minus self. Click → opens DM (`dm_<sortedPair>`), creating thread + adding member if needed.
- **Assistants** section: `usePresence().byRole.assistant`. Click → DM with that agent.

**TopControl** (`top-control.tsx`) — fully decoupled from the open thread:

- Agent dropdown (online assistants from `usePresence`).
- Channel dropdown (channels from `useThreads`).
- "Ping in channel" → POST `<agent.webhookUrl>/ping-channel` with `{channel_id, requested_by: {id, name}}`.
- "Ping me direct" → POST `<agent.webhookUrl>/ping-direct` with `{user_id, user_name, requested_by}`.
- Webhook URL map (`AGENT_WEBHOOKS`) lives in `agents.ts`: `agent-a → :9100`, `agent-b → :9101`, `agent-c → :9102`.

**ThreadPanel** — same as `stock-assistant`'s, plus a header showing `# <channel>` or `DM with <other.name>`. Streaming render (typing animation) uses the existing `stream:start/delta/end` plumbing in the React store — no new code needed.

`<ChatProvider onThreadInvited>` auto-opens a freshly-pinged DM in the requester's tab (same pattern stock-assistant's alert webhook uses).

---

## Verification

### Library tests (run via existing `uv run poe test` / `npm test`)

`packages/server-python/tests/test_presence.py`:
- First connect of `agent-a` broadcasts one `presence:joined`; second concurrent socket of `agent-a` broadcasts none.
- Closing one of two sockets keeps identity online (no broadcast); closing the last broadcasts `presence:left`.
- `GET /presence` returns the snapshot for the caller's tenant scope.
- Self-presence: a connecting socket does not receive its own `presence:joined`.
- With `namespace_keys` configured, presence frames stay within tenant.

`packages/client-python/tests/test_presence_handlers.py`:
- `@client.on_presence_joined()` fires on incoming frame; `await client.rest.list_presence()` round-trips against a real `ChatServer`.

`packages/client-react/tests/usePresence.test.ts`:
- Hook hydrates from REST mock; pushed `presence:joined` adds an entry; `presence:left` removes it; `byRole` partition is correct.

### Example verification (manual checklist in `team-communication/README.md`)

1. Start server + 3 agents + frontend (5 terminals).
2. Open 2 browser tabs → each shows the other in Users sidebar; both show all 3 Agents.
3. Close a tab → the other tab's Users list updates within socket-disconnect latency.
4. Click `#general` in tab A, send "hi" → tab B sees it in `#general`.
5. Click `Bob` in tab A → DM opens; the new DM thread doesn't appear in any other user's sidebar.
6. TopControl: pick Agent B + `#general` → "Ping in channel" → `#general` shows `@Alice <streamed Agent-B message>` to all tabs (typing visible).
7. TopControl: pick Agent C → "Ping me direct" → a new DM with Agent C auto-opens in your tab only; message streams in.

---

## Trade-offs and follow-ups

- **In-memory presence registry.** Restart wipes state. Acceptable here (matches `InMemoryChatStore`'s ephemeral semantics). For a Postgres-backed server with multiple replicas, presence would need cross-replica sync (Redis pubsub or socket.io's adapter). Out of scope.
- **No `presence:left` debouncing.** A user with one tab refreshing will briefly disappear and reappear. Easy follow-up if it becomes an issue.
- **Custom `list_threads` wrapper in the example.** Cleaner long-term: support a per-thread visibility predicate in the library's `list_threads`. Deferred — wrapping at the example layer is one route handler and avoids API churn before we know we want it.
- **Webhook URL map in the React client.** Hard-coded localhost ports. Acceptable for an example; production deployments would use env vars.
- **`recipients` not used for channel pings.** Mention is text-only (`@name`); the `recipients` field stays semantic. We could opt to populate it for the pinged user; deferred for simplicity.
