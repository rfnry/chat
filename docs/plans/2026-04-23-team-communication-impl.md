# team-communication Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a first-class presence primitive to `rfnry-chat` (protocol + server + Python client + React client), then build a Slack-shaped example (`team-communication`) that demonstrates channels, DMs, three independently-running AI agents, and a proactive ping control where agents stream LLM-generated messages to users or channels.

**Architecture:** Bottom-up. Protocol types land first, then server registry + broadcaster + REST, then each client adds dispatch + hooks/decorators. Example server consumes the new `authorize` hybrid (tenant for channels, membership for DMs); example agents consume the streaming `Run` API; example React consumes `usePresence()`. Refcount-based presence (per-identity, broadcast on 0→1 / 1→0 transitions only) keeps multi-tab and reconnects silent.

**Tech Stack:** Python 3.11 + FastAPI + python-socketio + asyncpg + pytest (server, agents); TypeScript + React + zustand + TanStack Query + vitest (frontend); pydantic for protocol; uv + poethepoet for Python tooling; biome + tsup for the React package.

**Design doc:** `chat/docs/plans/2026-04-23-team-communication-design.md`

**Repos touched:**
- `rfnry/types` — protocol additions (`chat-python`, `chat-typescript`)
- `rfnry/chat` — `server-python`, `client-python`, `client-react`
- `rfnry/yard` — new `examples/rfnry-chat/team-communication/` directory

**Worktree note:** Before starting, set up isolated worktrees for each repo touched (use `superpowers:using-git-worktrees`). Library-vs-example PR boundary: phases 1–4 are one library PR; phases 5–7 are a separate example PR that depends on the library being merged (or installed as an editable path during dev).

---

## Phase 1 — Protocol (`rfnry/types`)

### Task 1.1: Python `presence.py` module

**Files:**
- Create: `types/packages/chat-python/src/rfnry_chat_protocol/presence.py`
- Test: `types/packages/chat-python/tests/test_presence.py`

**Step 1: Write the failing test**

```python
# types/packages/chat-python/tests/test_presence.py
from datetime import UTC, datetime
from rfnry_chat_protocol import (
    AssistantIdentity,
    PresenceJoinedFrame,
    PresenceLeftFrame,
    PresenceSnapshot,
    UserIdentity,
)


def test_presence_snapshot_round_trips():
    snap = PresenceSnapshot(
        members=[
            UserIdentity(id="u_a", name="Alice", metadata={}),
            AssistantIdentity(id="agent-a", name="Agent A", metadata={}),
        ]
    )
    payload = snap.model_dump(mode="json", by_alias=True)
    parsed = PresenceSnapshot.model_validate(payload)
    assert {m.id for m in parsed.members} == {"u_a", "agent-a"}


def test_presence_joined_frame_round_trips():
    frame = PresenceJoinedFrame(
        identity=UserIdentity(id="u_a", name="Alice", metadata={}),
        at=datetime(2026, 4, 23, 12, 0, tzinfo=UTC),
    )
    payload = frame.model_dump(mode="json", by_alias=True)
    parsed = PresenceJoinedFrame.model_validate(payload)
    assert parsed.identity.id == "u_a"
    assert parsed.at == frame.at


def test_presence_left_frame_round_trips():
    frame = PresenceLeftFrame(
        identity=AssistantIdentity(id="agent-a", name="Agent A", metadata={}),
        at=datetime(2026, 4, 23, 12, 5, tzinfo=UTC),
    )
    payload = frame.model_dump(mode="json", by_alias=True)
    parsed = PresenceLeftFrame.model_validate(payload)
    assert parsed.identity.id == "agent-a"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/frndvrgs/software/rfnry/types/packages/chat-python
uv run pytest tests/test_presence.py -v
```

Expected: FAIL with `ImportError: cannot import name 'PresenceSnapshot'`.

**Step 3: Implement the module**

```python
# types/packages/chat-python/src/rfnry_chat_protocol/presence.py
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from rfnry_chat_protocol.identity import Identity


class PresenceSnapshot(BaseModel):
    """Initial snapshot of identities currently online within a tenant scope."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    members: list[Identity]


class PresenceJoinedFrame(BaseModel):
    """Transient frame: an identity went from 0 to 1 active sockets."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    identity: Identity
    at: datetime


class PresenceLeftFrame(BaseModel):
    """Transient frame: an identity went from 1 to 0 active sockets."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    identity: Identity
    at: datetime
```

**Step 4: Re-export from barrel**

Modify: `types/packages/chat-python/src/rfnry_chat_protocol/__init__.py`

Add to imports + `__all__`:
```python
from rfnry_chat_protocol.presence import (
    PresenceJoinedFrame,
    PresenceLeftFrame,
    PresenceSnapshot,
)
```

**Step 5: Run tests to verify pass**

```bash
uv run pytest tests/test_presence.py -v
```

Expected: 3 passed.

**Step 6: Commit**

```bash
cd /home/frndvrgs/software/rfnry/types
git add packages/chat-python/src/rfnry_chat_protocol/presence.py \
        packages/chat-python/src/rfnry_chat_protocol/__init__.py \
        packages/chat-python/tests/test_presence.py
git commit -m "feat(chat-python): add Presence{Snapshot,JoinedFrame,LeftFrame} types"
```

---

### Task 1.2: TypeScript `presence.ts` module

**Files:**
- Create: `types/packages/chat-typescript/src/presence.ts`
- Test: `types/packages/chat-typescript/tests/presence.test.ts`

**Step 1: Write the failing test**

```typescript
// types/packages/chat-typescript/tests/presence.test.ts
import { describe, expect, it } from 'vitest'
import {
  parsePresenceJoinedFrame,
  parsePresenceLeftFrame,
  parsePresenceSnapshot,
} from '../src/presence'

describe('presence parsers', () => {
  it('parses a snapshot', () => {
    const snap = parsePresenceSnapshot({
      members: [
        { role: 'user', id: 'u_a', name: 'Alice', metadata: {} },
        { role: 'assistant', id: 'agent-a', name: 'Agent A', metadata: {} },
      ],
    })
    expect(snap.members.map((m) => m.id).sort()).toEqual(['agent-a', 'u_a'])
  })

  it('parses a joined frame', () => {
    const frame = parsePresenceJoinedFrame({
      identity: { role: 'user', id: 'u_a', name: 'Alice', metadata: {} },
      at: '2026-04-23T12:00:00Z',
    })
    expect(frame.identity.id).toBe('u_a')
    expect(frame.at).toBe('2026-04-23T12:00:00Z')
  })

  it('parses a left frame', () => {
    const frame = parsePresenceLeftFrame({
      identity: { role: 'assistant', id: 'agent-a', name: 'Agent A', metadata: {} },
      at: '2026-04-23T12:05:00Z',
    })
    expect(frame.identity.id).toBe('agent-a')
  })

  it('rejects malformed snapshot', () => {
    expect(() => parsePresenceSnapshot({ members: 'nope' })).toThrow(/members/)
  })
})
```

**Step 2: Run test to verify it fails**

```bash
cd /home/frndvrgs/software/rfnry/types/packages/chat-typescript
npx vitest run tests/presence.test.ts
```

Expected: FAIL — module not found.

**Step 3: Implement the module**

```typescript
// types/packages/chat-typescript/src/presence.ts
import type { Identity, IdentityWire } from './identity'
import { parseIdentity } from './identity'

export type PresenceSnapshot = { members: Identity[] }
export type PresenceJoinedFrame = { identity: Identity; at: string }
export type PresenceLeftFrame = { identity: Identity; at: string }

export type PresenceSnapshotWire = { members: IdentityWire[] }
export type PresenceJoinedFrameWire = { identity: IdentityWire; at: string }
export type PresenceLeftFrameWire = { identity: IdentityWire; at: string }

export function parsePresenceSnapshot(raw: unknown): PresenceSnapshot {
  if (typeof raw !== 'object' || raw === null) {
    throw new Error(`invalid presence snapshot: ${JSON.stringify(raw)}`)
  }
  const record = raw as Record<string, unknown>
  if (!Array.isArray(record.members)) {
    throw new Error(`invalid presence snapshot members: ${JSON.stringify(raw)}`)
  }
  return { members: record.members.map(parseIdentity) }
}

export function parsePresenceJoinedFrame(raw: unknown): PresenceJoinedFrame {
  if (typeof raw !== 'object' || raw === null) {
    throw new Error(`invalid presence joined frame: ${JSON.stringify(raw)}`)
  }
  const record = raw as Record<string, unknown>
  if (typeof record.at !== 'string') {
    throw new Error(`invalid presence joined frame at: ${JSON.stringify(raw)}`)
  }
  return { identity: parseIdentity(record.identity), at: record.at }
}

export function parsePresenceLeftFrame(raw: unknown): PresenceLeftFrame {
  if (typeof raw !== 'object' || raw === null) {
    throw new Error(`invalid presence left frame: ${JSON.stringify(raw)}`)
  }
  const record = raw as Record<string, unknown>
  if (typeof record.at !== 'string') {
    throw new Error(`invalid presence left frame at: ${JSON.stringify(raw)}`)
  }
  return { identity: parseIdentity(record.identity), at: record.at }
}
```

> **Note:** check whether `parseIdentity` is already exported from `identity.ts`. If not, factor a small helper out of the existing event parser (`event.ts` has the inline `toIdentityInternal`). Keep the change minimal.

**Step 4: Re-export from `main.ts`**

```typescript
// types/packages/chat-typescript/src/main.ts
export * from './presence'
```

**Step 5: Run tests to verify pass**

```bash
npx vitest run tests/presence.test.ts
```

Expected: 4 passed.

**Step 6: Commit**

```bash
cd /home/frndvrgs/software/rfnry/types
git add packages/chat-typescript/src/presence.ts \
        packages/chat-typescript/src/main.ts \
        packages/chat-typescript/tests/presence.test.ts
git commit -m "feat(chat-typescript): add Presence{Snapshot,JoinedFrame,LeftFrame} parsers"
```

---

## Phase 2 — Server presence (`rfnry/chat/packages/server-python`)

### Task 2.1: `_PresenceRegistry` class

**Files:**
- Create: `chat/packages/server-python/src/rfnry_chat_server/server/presence.py`
- Test: `chat/packages/server-python/tests/server/test_presence_registry.py`

**Step 1: Write the failing test**

```python
# tests/server/test_presence_registry.py
import pytest
from rfnry_chat_protocol import UserIdentity
from rfnry_chat_server.server.presence import PresenceRegistry


@pytest.mark.asyncio
async def test_first_socket_returns_true_then_false():
    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    assert await reg.add("u_a", "sid1", alice, tenant_path="/") is True
    assert await reg.add("u_a", "sid2", alice, tenant_path="/") is False


@pytest.mark.asyncio
async def test_last_socket_drop_returns_true():
    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    await reg.add("u_a", "sid1", alice, tenant_path="/")
    await reg.add("u_a", "sid2", alice, tenant_path="/")
    was_last, ident, tp = await reg.remove("u_a", "sid1")
    assert was_last is False
    assert ident is None
    was_last, ident, tp = await reg.remove("u_a", "sid2")
    assert was_last is True
    assert ident is not None and ident.id == "u_a"
    assert tp == "/"


@pytest.mark.asyncio
async def test_list_for_tenant_filters_by_path():
    reg = PresenceRegistry()
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    bob = UserIdentity(id="u_b", name="Bob", metadata={})
    await reg.add("u_a", "sid1", alice, tenant_path="/A")
    await reg.add("u_b", "sid2", bob, tenant_path="/B")
    members_a = await reg.list_for_tenant("/A")
    members_b = await reg.list_for_tenant("/B")
    assert {m.id for m in members_a} == {"u_a"}
    assert {m.id for m in members_b} == {"u_b"}


@pytest.mark.asyncio
async def test_remove_unknown_sid_is_noop():
    reg = PresenceRegistry()
    was_last, ident, tp = await reg.remove("u_unknown", "sid_unknown")
    assert was_last is False
    assert ident is None
    assert tp is None
```

**Step 2: Run test to verify it fails**

```bash
cd /home/frndvrgs/software/rfnry/chat/packages/server-python
uv run pytest tests/server/test_presence_registry.py -v
```

Expected: FAIL — `ModuleNotFoundError: rfnry_chat_server.server.presence`.

**Step 3: Implement the registry**

```python
# src/rfnry_chat_server/server/presence.py
from __future__ import annotations

import asyncio

from rfnry_chat_protocol import Identity


class PresenceRegistry:
    """In-memory refcount of which identities have at least one live socket.

    Returned booleans indicate edge transitions only — `add` returns True on
    0→1 (so the caller broadcasts `presence:joined`), `remove` returns True
    on 1→0 (so the caller broadcasts `presence:left`). Other tab opens/closes
    are silent.
    """

    def __init__(self) -> None:
        self._sids: dict[str, set[str]] = {}
        self._identities: dict[str, Identity] = {}
        self._tenant_paths: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def add(
        self,
        identity_id: str,
        sid: str,
        identity: Identity,
        *,
        tenant_path: str,
    ) -> bool:
        async with self._lock:
            sids = self._sids.setdefault(identity_id, set())
            was_empty = not sids
            sids.add(sid)
            self._identities[identity_id] = identity
            self._tenant_paths[identity_id] = tenant_path
            return was_empty

    async def remove(
        self,
        identity_id: str,
        sid: str,
    ) -> tuple[bool, Identity | None, str | None]:
        async with self._lock:
            sids = self._sids.get(identity_id)
            if not sids:
                return False, None, None
            sids.discard(sid)
            if sids:
                return False, None, None
            del self._sids[identity_id]
            ident = self._identities.pop(identity_id, None)
            tp = self._tenant_paths.pop(identity_id, None)
            return True, ident, tp

    async def list_for_tenant(self, tenant_path: str) -> list[Identity]:
        async with self._lock:
            return [
                self._identities[iid]
                for iid, tp in self._tenant_paths.items()
                if tp == tenant_path
            ]
```

**Step 4: Run tests to verify pass**

```bash
uv run pytest tests/server/test_presence_registry.py -v
```

Expected: 4 passed.

**Step 5: Commit**

```bash
git add src/rfnry_chat_server/server/presence.py \
        tests/server/test_presence_registry.py
git commit -m "feat(server): PresenceRegistry with refcount-based edge detection"
```

---

### Task 2.2: Wire registry into `ChatServer`

**Files:**
- Modify: `chat/packages/server-python/src/rfnry_chat_server/server/chat_server.py`
- Modify: `chat/packages/server-python/src/rfnry_chat_server/__init__.py` (re-export)

**Step 1: Read the current `ChatServer.__init__`**

```bash
grep -n "def __init__" /home/frndvrgs/software/rfnry/chat/packages/server-python/src/rfnry_chat_server/server/chat_server.py
```

**Step 2: Add registry construction**

In `ChatServer.__init__`, after the existing initializers, add:

```python
from rfnry_chat_server.server.presence import PresenceRegistry  # at top of file
...
self.presence = PresenceRegistry()
```

**Step 3: Re-export `PresenceRegistry`**

Modify `src/rfnry_chat_server/__init__.py`:
```python
from rfnry_chat_server.server.presence import PresenceRegistry
# add to __all__
```

**Step 4: Verify no test regression**

```bash
uv run pytest -x --ignore=tests/integration --ignore=tests/socketio/test_live_integration.py
```

Expected: all existing tests still pass.

**Step 5: Commit**

```bash
git add src/rfnry_chat_server/server/chat_server.py \
        src/rfnry_chat_server/__init__.py
git commit -m "feat(server): mount PresenceRegistry on ChatServer"
```

---

### Task 2.3: Broadcaster methods + presence room

**Files:**
- Modify: `chat/packages/server-python/src/rfnry_chat_server/broadcast/socketio.py`
- Modify: `chat/packages/server-python/src/rfnry_chat_server/broadcast/protocol.py` (Protocol class)
- Modify: `chat/packages/server-python/src/rfnry_chat_server/broadcast/recording.py` (Recording broadcaster used in tests)
- Test: `chat/packages/server-python/tests/broadcast/test_presence_broadcast.py`

**Step 1: Write the failing test**

```python
# tests/broadcast/test_presence_broadcast.py
import pytest
from datetime import UTC, datetime
from rfnry_chat_protocol import PresenceJoinedFrame, PresenceLeftFrame, UserIdentity
from rfnry_chat_server.broadcast.recording import RecordingBroadcaster


@pytest.mark.asyncio
async def test_records_presence_joined():
    bc = RecordingBroadcaster()
    frame = PresenceJoinedFrame(
        identity=UserIdentity(id="u_a", name="Alice", metadata={}),
        at=datetime(2026, 4, 23, tzinfo=UTC),
    )
    await bc.broadcast_presence_joined(frame, tenant_path="/", skip_sid=None)
    assert bc.presence_joined == [frame]


@pytest.mark.asyncio
async def test_records_presence_left():
    bc = RecordingBroadcaster()
    frame = PresenceLeftFrame(
        identity=UserIdentity(id="u_a", name="Alice", metadata={}),
        at=datetime(2026, 4, 23, tzinfo=UTC),
    )
    await bc.broadcast_presence_left(frame, tenant_path="/")
    assert bc.presence_left == [frame]
```

**Step 2: Run test, verify it fails**

```bash
uv run pytest tests/broadcast/test_presence_broadcast.py -v
```

Expected: FAIL — methods don't exist.

**Step 3: Add `_presence_room` + broadcaster methods (`socketio.py`)**

```python
def _presence_room(tenant_path: str) -> str:
    return f"presence:{tenant_path}"


# in SocketIOBroadcaster:
async def broadcast_presence_joined(
    self,
    frame: PresenceJoinedFrame,
    *,
    tenant_path: str,
    skip_sid: str | None = None,
    namespace: str | None = None,
) -> None:
    await self._sio.emit(
        "presence:joined",
        frame.model_dump(mode="json", by_alias=True),
        room=_presence_room(tenant_path),
        skip_sid=skip_sid,
        namespace=namespace or "/",
    )

async def broadcast_presence_left(
    self,
    frame: PresenceLeftFrame,
    *,
    tenant_path: str,
    namespace: str | None = None,
) -> None:
    await self._sio.emit(
        "presence:left",
        frame.model_dump(mode="json", by_alias=True),
        room=_presence_room(tenant_path),
        namespace=namespace or "/",
    )
```

Add corresponding abstract method declarations in `protocol.py`'s `Broadcaster` Protocol, and concrete recording variants in `recording.py`:

```python
# recording.py — add:
self.presence_joined: list[PresenceJoinedFrame] = []
self.presence_left: list[PresenceLeftFrame] = []

async def broadcast_presence_joined(self, frame, *, tenant_path, skip_sid=None, namespace=None):
    self.presence_joined.append(frame)

async def broadcast_presence_left(self, frame, *, tenant_path, namespace=None):
    self.presence_left.append(frame)
```

**Step 4: Run tests to verify pass**

```bash
uv run pytest tests/broadcast/test_presence_broadcast.py -v
```

Expected: 2 passed.

**Step 5: Commit**

```bash
git add src/rfnry_chat_server/broadcast/ tests/broadcast/test_presence_broadcast.py
git commit -m "feat(broadcast): presence:joined/presence:left broadcaster methods"
```

---

### Task 2.4: `on_connect` enters presence room + broadcasts joined

**Files:**
- Modify: `chat/packages/server-python/src/rfnry_chat_server/socketio/server.py`
- Test: `chat/packages/server-python/tests/socketio/test_presence_lifecycle.py` (new)

**Step 1: Write the failing test (uses live integration pattern)**

Pattern after `tests/socketio/test_live_integration.py`. The test:

1. Spins up a `ChatServer` with `RecordingBroadcaster` swapped in (or use the standard one and assert via a connected listener client).
2. Connects identity `agent-a` once → expects 1 `presence:joined` recorded.
3. Connects identity `agent-a` *again* (second socket) → no new broadcast (still 1).
4. Disconnects one of the two → no `presence:left`.
5. Disconnects the second → 1 `presence:left`.

```python
# tests/socketio/test_presence_lifecycle.py
import pytest
from rfnry_chat_protocol import AssistantIdentity
from rfnry_chat_server import ChatServer, InMemoryChatStore

# import the same live test harness used by test_live_integration.py
from tests.socketio.test_live_integration import _start_server, _connect_client


@pytest.mark.asyncio
async def test_refcount_broadcasts_only_on_edges():
    server = ChatServer(store=InMemoryChatStore())
    async with _start_server(server) as base_url:
        agent = AssistantIdentity(id="agent-a", name="Agent A", metadata={})
        observer_events: list[dict] = []
        # observer client (different identity) joins to receive presence frames
        observer = AssistantIdentity(id="observer", name="Observer", metadata={})
        async with _connect_client(base_url, observer) as obs_client:
            obs_client.on("presence:joined", lambda data: observer_events.append(("joined", data)))
            obs_client.on("presence:left", lambda data: observer_events.append(("left", data)))

            # first agent socket
            async with _connect_client(base_url, agent) as a1:
                await _sleep_for_propagation()
                # second agent socket (concurrent)
                async with _connect_client(base_url, agent) as a2:
                    await _sleep_for_propagation()

                # both sockets up — only ONE joined recorded
                joined_count = sum(1 for tag, _ in observer_events if tag == "joined")
                assert joined_count == 1

                # close one — no left yet
                await a2.disconnect()
                await _sleep_for_propagation()
                left_count = sum(1 for tag, _ in observer_events if tag == "left")
                assert left_count == 0

            # second close — left fires
            await _sleep_for_propagation()
            left_count = sum(1 for tag, _ in observer_events if tag == "left")
            assert left_count == 1
```

> **Note:** `_start_server` and `_connect_client` may need light extraction from `test_live_integration.py` into `tests/socketio/_live.py`. If extraction is more than ~30 lines, do it as a separate prep commit.

**Step 2: Run test, verify it fails**

```bash
uv run pytest tests/socketio/test_presence_lifecycle.py -v
```

Expected: FAIL — `presence:joined` never fires.

**Step 3: Wire `on_connect` in `socketio/server.py`**

In `ThreadNamespace.on_connect`, after the existing `enter_room(sid, tenant_room_name)`:

```python
from datetime import UTC, datetime
from rfnry_chat_protocol import PresenceJoinedFrame
from rfnry_chat_server.broadcast.socketio import _presence_room  # may need export

# derive a presence-room key from the tenant scope (reuse derive_namespace_path for consistency)
tenant_path = _tenant_path_for(identity_tenant, namespace_keys=ns_keys)
await self.enter_room(sid, _presence_room(tenant_path))

is_first = await self._server.presence.add(
    identity.id, sid, identity, tenant_path=tenant_path
)
if is_first:
    await self._server.broadcaster.broadcast_presence_joined(
        PresenceJoinedFrame(identity=identity, at=datetime.now(UTC)),
        tenant_path=tenant_path,
        skip_sid=sid,                       # don't echo to the joining socket
        namespace=concrete_ns,
    )
```

`_tenant_path_for` is a small helper that wraps `derive_namespace_path(...)` and falls back to `"/"` when `namespace_keys is None`. Add it next to `_tenant_room` (or extract from there).

**Step 4: Run test to verify joined edge passes (left will still fail)**

```bash
uv run pytest tests/socketio/test_presence_lifecycle.py -v
```

Expected: joined count is 1; left count assertion still fails (no `on_disconnect` yet).

**Step 5: Commit**

```bash
git add src/rfnry_chat_server/socketio/server.py
git commit -m "feat(socketio): broadcast presence:joined on first socket per identity"
```

---

### Task 2.5: `on_disconnect` removes from registry + broadcasts left

**Files:**
- Modify: `chat/packages/server-python/src/rfnry_chat_server/socketio/server.py`

**Step 1: Add `on_disconnect` handler**

Inside `ThreadNamespace`:

```python
async def on_disconnect(self, sid: str, *_args: Any) -> None:
    try:
        session = await self.get_session(sid)
    except KeyError:
        return
    identity: Identity | None = session.get("identity")
    if identity is None:
        return
    is_last, _ident, tenant_path = await self._server.presence.remove(identity.id, sid)
    if is_last and tenant_path is not None:
        await self._server.broadcaster.broadcast_presence_left(
            PresenceLeftFrame(identity=identity, at=datetime.now(UTC)),
            tenant_path=tenant_path,
            namespace=session.get("namespace") or "/",
        )
```

> **Note:** python-socketio 5.12+ passes a `reason` arg to disconnect; the existing `trigger_event` already handles the fallback.

**Step 2: Run test, verify it now passes**

```bash
uv run pytest tests/socketio/test_presence_lifecycle.py -v
```

Expected: PASS (1 joined, 1 left, no echoes).

**Step 3: Run full test suite for regression**

```bash
uv run poe check && uv run poe typecheck && uv run pytest -x --ignore=tests/integration
```

Expected: green.

**Step 4: Commit**

```bash
git add src/rfnry_chat_server/socketio/server.py
git commit -m "feat(socketio): broadcast presence:left on last socket per identity"
```

---

### Task 2.6: REST `GET /chat/presence` endpoint

**Files:**
- Create: `chat/packages/server-python/src/rfnry_chat_server/server/rest/presence.py`
- Modify: `chat/packages/server-python/src/rfnry_chat_server/server/rest/__init__.py` (mount router)
- Test: `chat/packages/server-python/tests/server/test_rest_presence.py`

**Step 1: Write the failing test**

Pattern after `tests/server/test_rest_threads.py`. Spin up a `ChatServer`, seed two presence entries via `server.presence.add(...)`, hit `GET /chat/presence` as a third caller, expect 200 + both members in the snapshot. Add a tenant-isolation test where caller's tenant_path is `/A` and the seeded entries are in `/B` — expects empty.

```python
# tests/server/test_rest_presence.py — sketch
@pytest.mark.asyncio
async def test_presence_snapshot_returns_other_members(client_factory):
    server = ChatServer(store=InMemoryChatStore())
    alice = UserIdentity(id="u_a", name="Alice", metadata={})
    bob = UserIdentity(id="u_b", name="Bob", metadata={})
    await server.presence.add("u_a", "sid1", alice, tenant_path="/")
    await server.presence.add("u_b", "sid2", bob, tenant_path="/")

    async with client_factory(server, identity=UserIdentity(id="u_c", name="Carol", metadata={})) as http:
        resp = await http.get("/chat/presence")
    assert resp.status_code == 200
    body = resp.json()
    assert {m["id"] for m in body["members"]} == {"u_a", "u_b"}
```

**Step 2: Run test, verify it fails**

Expected: 404 (route doesn't exist).

**Step 3: Implement the route**

```python
# src/rfnry_chat_server/server/rest/presence.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from rfnry_chat_protocol import PresenceSnapshot

from rfnry_chat_server.server.rest.deps import (
    PresenceDeps,        # new — wraps server + tenant_path resolution
    get_presence_deps,
)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/presence", response_model=PresenceSnapshot)
    async def get_presence(
        deps: PresenceDeps = Depends(get_presence_deps),
    ) -> PresenceSnapshot:
        members = await deps.server.presence.list_for_tenant(deps.tenant_path)
        # Exclude the caller themselves (they know they're online).
        members = [m for m in members if m.id != deps.identity.id]
        return PresenceSnapshot(members=members)

    return router
```

`PresenceDeps` and `get_presence_deps` follow the existing pattern in `rest/deps.py` for `ThreadDeps`. They resolve identity from the auth header and compute tenant_path from `derive_namespace_path(...)` (or `"/"` when namespace_keys is None).

Mount in `rest/__init__.py` next to the threads router.

**Step 4: Run tests to verify pass**

```bash
uv run pytest tests/server/test_rest_presence.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/rfnry_chat_server/server/rest/presence.py \
        src/rfnry_chat_server/server/rest/__init__.py \
        src/rfnry_chat_server/server/rest/deps.py \
        tests/server/test_rest_presence.py
git commit -m "feat(rest): GET /chat/presence returns tenant-scoped snapshot"
```

---

## Phase 3 — Python client (`rfnry/chat/packages/client-python`)

### Task 3.1: REST `list_presence` method

**Files:**
- Modify: `chat/packages/client-python/src/rfnry_chat_client/transport/rest.py`
- Test: `chat/packages/client-python/tests/test_rest.py` (extend)

**Step 1: Write the failing test**

```python
# tests/test_rest.py — append
@pytest.mark.asyncio
async def test_list_presence_round_trips(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="http://server/chat/presence",
        json={"members": [{"role": "user", "id": "u_a", "name": "Alice", "metadata": {}}]},
    )
    rest = RestTransport(base_url="http://server", identity_header={"x-rfnry-identity": "{}"})
    snap = await rest.list_presence()
    assert snap.members[0].id == "u_a"
```

**Step 2: Run test, verify it fails**

Expected: `AttributeError: 'RestTransport' object has no attribute 'list_presence'`.

**Step 3: Implement**

```python
# transport/rest.py — add
from rfnry_chat_protocol import PresenceSnapshot

async def list_presence(self) -> PresenceSnapshot:
    resp = await self._client.get(f"{self._base_url}/chat/presence", headers=self._headers())
    resp.raise_for_status()
    return PresenceSnapshot.model_validate(resp.json())
```

**Step 4: Run tests to verify pass + commit**

```bash
uv run pytest tests/test_rest.py -v
git add src/rfnry_chat_client/transport/rest.py tests/test_rest.py
git commit -m "feat(client-python): rest.list_presence()"
```

---

### Task 3.2: Frame dispatch for `presence:joined` / `presence:left`

**Files:**
- Modify: `chat/packages/client-python/src/rfnry_chat_client/dispatch.py`
- Modify: `chat/packages/client-python/src/rfnry_chat_client/client.py`
- Test: `chat/packages/client-python/tests/test_dispatch.py` (extend)

**Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_dispatches_presence_joined(stub_client):
    received: list[PresenceJoinedFrame] = []

    @stub_client.on_presence_joined()
    async def handler(frame):
        received.append(frame)

    await stub_client._dispatch_raw(
        "presence:joined",
        {"identity": {"role": "user", "id": "u_a", "name": "A", "metadata": {}},
         "at": "2026-04-23T00:00:00Z"},
    )
    assert received[0].identity.id == "u_a"
```

(Extend `tests/test_dispatch.py`'s existing `stub_client` fixture if needed.)

**Step 2: Run, verify FAIL.**

**Step 3: Implement**

In `client.py`, add list attrs in `__init__`:
```python
self._presence_joined_handlers: list[Callable] = []
self._presence_left_handlers: list[Callable] = []

def on_presence_joined(self):
    def deco(fn): self._presence_joined_handlers.append(fn); return fn
    return deco

def on_presence_left(self):
    def deco(fn): self._presence_left_handlers.append(fn); return fn
    return deco
```

In `dispatch.py`, in the socket-on registration block:
```python
@self._sio.on("presence:joined", namespace=ns)
async def _on_presence_joined(payload):
    frame = PresenceJoinedFrame.model_validate(payload)
    for handler in self._client._presence_joined_handlers:
        await handler(frame)

@self._sio.on("presence:left", namespace=ns)
async def _on_presence_left(payload):
    frame = PresenceLeftFrame.model_validate(payload)
    for handler in self._client._presence_left_handlers:
        await handler(frame)
```

**Step 4: Run tests, verify pass + commit**

```bash
uv run pytest tests/test_dispatch.py -v
git add src/rfnry_chat_client/dispatch.py src/rfnry_chat_client/client.py tests/test_dispatch.py
git commit -m "feat(client-python): on_presence_joined / on_presence_left decorators"
```

---

### Task 3.3: End-to-end integration test

**Files:**
- Create: `chat/packages/client-python/tests/integration/test_presence.py`

**Step 1: Write the test**

Boots a real `ChatServer` (use existing `tests/integration/conftest.py` helper if present), opens two `ChatClient` instances with different identities, asserts:
1. Client B receives a `presence:joined` for client A within 2s of A connecting.
2. `await b.rest.list_presence()` includes A.
3. When A disconnects, client B receives a `presence:left`.

**Step 2: Run, iterate, commit**

```bash
uv run pytest tests/integration/test_presence.py -v
git add tests/integration/test_presence.py
git commit -m "test(client-python): end-to-end presence lifecycle"
```

---

## Phase 4 — React client (`rfnry/chat/packages/client-react`)

### Task 4.1: Presence zustand slice

**Files:**
- Create: `chat/packages/client-react/src/store/presence.ts`
- Test: `chat/packages/client-react/tests/store/presence.test.ts`

**Step 1: Write failing test**

```typescript
import { describe, expect, it } from 'vitest'
import { createPresenceSlice } from '../../src/store/presence'

const alice = { role: 'user', id: 'u_a', name: 'Alice', metadata: {} } as const
const agentA = { role: 'assistant', id: 'agent-a', name: 'Agent A', metadata: {} } as const

describe('presence slice', () => {
  it('hydrates from snapshot', () => {
    const s = createPresenceSlice()
    s.hydrate({ members: [alice, agentA] })
    expect(s.list().map((m) => m.id).sort()).toEqual(['agent-a', 'u_a'])
    expect(s.isHydrated()).toBe(true)
  })

  it('adds on joined', () => {
    const s = createPresenceSlice()
    s.hydrate({ members: [] })
    s.applyJoined({ identity: alice, at: '...' })
    expect(s.list()).toEqual([alice])
  })

  it('removes on left and dedupes joined', () => {
    const s = createPresenceSlice()
    s.hydrate({ members: [alice] })
    s.applyJoined({ identity: alice, at: '...' })   // dedupe
    expect(s.list()).toEqual([alice])
    s.applyLeft({ identity: alice, at: '...' })
    expect(s.list()).toEqual([])
  })
})
```

**Step 2: Run, verify FAIL.**

**Step 3: Implement** — small zustand store keyed by identity id (Map).

**Step 4: Pass + commit.**

---

### Task 4.2: REST helper `listPresence`

**Files:**
- Modify: `chat/packages/client-react/src/transport/rest.ts`
- Test: `chat/packages/client-react/tests/transport/rest.test.ts` (extend)

Mirror Task 3.1 in TypeScript.

---

### Task 4.3: Provider wires hydration + socket listeners

**Files:**
- Modify: `chat/packages/client-react/src/provider/ChatProvider.tsx`

In the connect effect, after the existing `socket.connect()` ack:

```typescript
const snapshot = await rest.listPresence()
presence.hydrate(snapshot)
socket.on('presence:joined', (raw) => presence.applyJoined(parsePresenceJoinedFrame(raw)))
socket.on('presence:left',   (raw) => presence.applyLeft(parsePresenceLeftFrame(raw)))
```

Cleanup in the effect's return: `socket.off(...)`.

Add a small contract test against a mocked socket + REST.

Commit.

---

### Task 4.4: `usePresence()` hook

**Files:**
- Create: `chat/packages/client-react/src/hooks/usePresence.ts`
- Modify: `chat/packages/client-react/src/main.ts` (re-export)
- Test: `chat/packages/client-react/tests/hooks/usePresence.test.tsx`

```typescript
export function usePresence() {
  const members = usePresenceStore((s) => s.list())
  const byRole = useMemo(() => ({
    user:      members.filter((m) => m.role === 'user'),
    assistant: members.filter((m) => m.role === 'assistant'),
    system:    members.filter((m) => m.role === 'system'),
  }), [members])
  const isHydrated = usePresenceStore((s) => s.isHydrated())
  return { members, byRole, isHydrated }
}
```

Test: render hook with a controlled provider, push a `presence:joined`, assert `byRole.user` updates.

**Commit.** End of Phase 4. PR-ready library milestone.

---

## Phase 5 — Example: server (`yard/examples/rfnry-chat/team-communication/server-python`)

### Task 5.1: Scaffold from `multi-tenant/server-python`

**Files:**
- Create: `yard/examples/rfnry-chat/team-communication/server-python/` (copy structure from `multi-tenant/server-python`)

```bash
cd /home/frndvrgs/software/rfnry/yard/examples/rfnry-chat
cp -r multi-tenant/server-python team-communication/server-python
# strip __pycache__, .venv, uv.lock — keep pyproject.toml + src/
```

Edit `pyproject.toml`: rename project to `team-communication-server`, keep deps identical.

**Commit:**

```bash
cd /home/frndvrgs/software/rfnry/yard
git add examples/rfnry-chat/team-communication/server-python/
git commit -m "feat(team-communication): scaffold server-python from multi-tenant"
```

---

### Task 5.2: Channel bootstrap + hybrid authorize

**Files:**
- Modify: `team-communication/server-python/src/chat.py`
- Modify: `team-communication/server-python/src/main.py` (call bootstrap in lifespan)

```python
# src/chat.py
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


async def bootstrap_channels(store):
    for cid, slug, label in CHANNELS:
        if await store.get_thread(cid) is None:
            await store.create_thread(
                Thread(
                    id=cid,
                    tenant={"channel": slug},
                    metadata={"kind": "channel", "label": label},
                    ...
                )
            )
```

> Adjust `store.create_thread` call signature to match `InMemoryChatStore.create_thread`'s actual params (check `chat/packages/server-python/src/rfnry_chat_server/store/memory/store.py:40`).

In `main.py`'s lifespan, after `await chat_server.start()`:
```python
await bootstrap_channels(chat_server.store)
```

**Smoke test:** `uv run poe dev`, then `curl http://localhost:8000/chat/threads -H 'x-rfnry-identity: {"id":"u_test","name":"T","role":"user","metadata":{"tenant":{"channel":"*"}}}'` returns both channels.

**Commit.**

---

### Task 5.3: Custom `/chat/threads` filter for DM hiding

**Files:**
- Modify: `team-communication/server-python/src/main.py`

Add a wrapper route mounted *before* the chat_server.router:

```python
@app.get("/chat/threads")
async def list_threads_filtered(request: Request):
    # delegate to the library handler, then drop DMs the caller isn't a member of.
    # For simplicity in the example, call store directly:
    page = await chat_server.store.list_threads(...)
    identity = _identity_from_headers(request.headers)   # parse x-rfnry-identity
    visible = []
    for t in page.items:
        if (t.metadata or {}).get("kind") == "dm":
            if not await chat_server.store.is_member(t.id, identity.id):
                continue
        visible.append(t)
    return {"items": [t.model_dump(...) for t in visible], "next_cursor": page.next_cursor}
```

> If wrapping the library route turns out to be ugly (FastAPI route precedence shenanigans), instead add an `app.middleware("http")` hook that mutates the response body for `/chat/threads` GET. Keep the implementation contained to `main.py`.

**Smoke test:** create a DM with member u_a only; u_b's GET /chat/threads should NOT include it.

**Commit.**

---

### Task 5.4: README

**Files:**
- Create: `team-communication/server-python/README.md`

Mirror `multi-tenant/server-python/README.md` shape: install, run, brief description of the hybrid authorize.

**Commit.**

---

## Phase 6 — Example: agents (`yard/examples/rfnry-chat/team-communication/client-python-{a,b,c}`)

### Task 6.1: Scaffold `client-python-a` from `stock-assistant/client-python`

```bash
cp -r yard/examples/rfnry-chat/stock-assistant/client-python \
      yard/examples/rfnry-chat/team-communication/client-python-a
# strip __pycache__, .venv, uv.lock
```

Edit `pyproject.toml`: rename to `team-communication-agent-a`, port `9100`.

**Commit.**

---

### Task 6.2: Channel discovery on connect + identity tenant

**Files:**
- Modify: `client-python-a/src/agent.py`
- Modify: `client-python-a/src/main.py`

In `agent.py`:

```python
ASSISTANT_ID = "agent-a"
ASSISTANT_NAME = "Agent A"
PERSONA_PROMPT = (
    "You are Agent A, an Engineering Manager AI on this team's chat. "
    "You're direct, terse, and code-aware. You write like an engineer who's busy "
    "but cares — short, no fluff, action-oriented. Avoid emojis."
)

IDENTITY = AssistantIdentity(
    id=ASSISTANT_ID,
    name=ASSISTANT_NAME,
    metadata={"tenant": {"channel": "*"}},
)
```

In `main.py`, replicate the multi-tenant pattern's `_discover_and_join`, but filter to `metadata.kind == "channel"`:

```python
async def _join_all_channels(client, joined):
    page = await client.rest.list_threads()
    for t in page["items"]:
        if (t.metadata or {}).get("kind") != "channel":
            continue
        if t.id in joined:
            continue
        await client.join_thread(t.id)
        joined.add(t.id)

async def lifespan(app):
    joined = set()
    async def on_connect():
        await _join_all_channels(client, joined)
    @client.on_invited()
    async def on_invited(frame):
        joined.add(frame.thread.id)
    agent_task = asyncio.create_task(client.run(on_connect=on_connect))
    ...
```

**Smoke test:** start server (Phase 5), start agent-a, verify in agent logs that it joined `ch_general` and `ch_engineering`.

**Commit.**

---

### Task 6.3: Subject pool + persona prompt

**Files:**
- Modify: `client-python-a/src/agent.py`

```python
AGENT_A_SUBJECTS = [
    "PR-1234 (refactor auth middleware) is ready for review",
    "main is red — flake on test_thread_invited",
    "design doc for the presence system landed in chat/docs",
    "p99 latency on /chat/threads doubled overnight — looking into it",
    "we should split the ChatServer god-class before it grows again",
]
```

**Commit.**

---

### Task 6.4: Streaming proactive message helper

**Files:**
- Create: `client-python-a/src/proactive.py`

```python
# src/proactive.py
import asyncio
from datetime import UTC, datetime

from rfnry_chat_client import ChatClient
from rfnry_chat_client.handler.send import HandlerSend
from rfnry_chat_protocol import RunError, TextPart

from src import provider
from src.agent import IDENTITY, PERSONA_PROMPT


async def stream_proactive_message(
    client: ChatClient,
    *,
    thread_id: str,
    subject: str,
    audience: str,                # "channel" or "direct DM"
    addressee_name: str,
    mention_inline: bool,
) -> None:
    anthropic = provider.build_anthropic()
    addressing = (
        f"Mention them inline as @{addressee_name}."
        if mention_inline
        else f"Address them once as {addressee_name}."
    )
    prompt = (
        f"You are reaching out proactively to {addressee_name} via a {audience}. "
        f"The topic on your mind: {subject}\n\n"
        f"Write a single short chat message (1-3 sentences) opening the conversation. "
        f"Stay in character. Don't double-greet. {addressing}"
    )

    if anthropic is None:
        # Stub fallback — one-shot, no streaming.
        await client.send_message(
            thread_id=thread_id,
            content=[TextPart(text=f"[stub {IDENTITY.name}] subject: {subject}")],
        )
        return

    run = await client.begin_run(thread_id=thread_id)
    try:
        send = HandlerSend(
            thread_id=thread_id,
            author=IDENTITY,
            client=client,
            run_id=run.id,
        )
        stream = send.message_stream()
        async with anthropic.messages.stream(
            model=provider.ANTHROPIC_MODEL,
            max_tokens=512,
            system=PERSONA_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as s:
            async for token in s.text_stream:
                await stream.delta(token)
        await stream.finalize()
        await client.end_run(run_id=run.id)
    except Exception as exc:
        await client.end_run(run_id=run.id, error=RunError(code="ping_failed", message=str(exc)))
        raise
```

> Verify the actual `send.message_stream()` API surface — adjust `delta`/`finalize` names against `chat/packages/client-python/src/rfnry_chat_client/handler/stream.py` if they differ.

**Commit.**

---

### Task 6.5: `/ping-channel` webhook

**Files:**
- Modify: `client-python-a/src/main.py`

```python
class PingChannelBody(BaseModel):
    channel_id: str
    requested_by: dict     # {id, name}


@app.post("/ping-channel")
async def ping_channel(body: PingChannelBody):
    subject = random.choice(AGENT_A_SUBJECTS)
    await stream_proactive_message(
        client,
        thread_id=body.channel_id,
        subject=subject,
        audience="channel",
        addressee_name=body.requested_by.get("name", "team"),
        mention_inline=True,
    )
    return {"ok": True, "subject": subject}
```

**Smoke test:** `curl -X POST http://localhost:9100/ping-channel -d '{"channel_id":"ch_general","requested_by":{"id":"u_dev","name":"Dev"}}' -H 'content-type: application/json'`. Open frontend, see streamed message in #general.

**Commit.**

---

### Task 6.6: `/ping-direct` webhook

**Files:**
- Modify: `client-python-a/src/main.py`

```python
def _dm_thread_id(a: str, b: str) -> str:
    return "dm_" + "__".join(sorted([a, b]))


class PingDirectBody(BaseModel):
    user_id: str
    user_name: str
    requested_by: dict


@app.post("/ping-direct")
async def ping_direct(body: PingDirectBody):
    user = UserIdentity(id=body.user_id, name=body.user_name)
    dm_id = _dm_thread_id(IDENTITY.id, body.user_id)
    thread, _ = await client.open_thread_with(
        message=None,
        invite=user,
        thread_id=dm_id,
        metadata={"kind": "dm"},
    )
    subject = random.choice(AGENT_A_SUBJECTS)
    await stream_proactive_message(
        client,
        thread_id=thread.id,
        subject=subject,
        audience="direct DM",
        addressee_name=body.user_name,
        mention_inline=False,
    )
    return {"ok": True, "thread_id": thread.id, "subject": subject}
```

> If `open_thread_with` doesn't support `message=None`, send an empty placeholder or restructure: create thread + add member directly, then call the streaming helper. Check the stock-assistant flow for the exact pattern.

**Smoke test:** `curl -X POST http://localhost:9100/ping-direct -d '{"user_id":"u_test","user_name":"Tester","requested_by":{"id":"u_test","name":"Tester"}}' -H 'content-type: application/json'`. Open a frontend tab logged in as `u_test`, see DM auto-open with streaming reply.

**Commit.**

---

### Task 6.7: Clone agent-a into agent-b and agent-c

```bash
cp -r yard/examples/rfnry-chat/team-communication/client-python-a \
      yard/examples/rfnry-chat/team-communication/client-python-b
cp -r yard/examples/rfnry-chat/team-communication/client-python-a \
      yard/examples/rfnry-chat/team-communication/client-python-c
```

For each, update:
- `pyproject.toml`: project name + port (`9101` for b, `9102` for c)
- `src/agent.py`: `ASSISTANT_ID`, `ASSISTANT_NAME`, `PERSONA_PROMPT`, `AGENT_*_SUBJECTS`

Personas:

**Agent B — Release Coordinator**
```
"You are Agent B, the Release Coordinator. You're calm, process-y, and "
"calendar-aware. You speak in dates and gates. You write like someone "
"keeping the trains running."
```
Subjects:
- "release cut for v0.42 moves to Friday — engineering needs to land 3 PRs by EOD Thu"
- "merge freeze starts tomorrow at 17:00 UTC for the mobile branch"
- "pre-prod canary is at 5% and clean for 2h — ready to ramp to 25%"
- "the rollback runbook is stale — last update was 6 months ago"
- "all green on the release dashboard, we're ship-ready"

**Agent C — Support Liaison**
```
"You are Agent C, the Support Liaison. You're empathetic and customer-voiced. "
"You translate user pain into engineering-actionable summaries without losing "
"the human signal."
```
Subjects:
- "customer (Acme Co) reports threads disappearing on refresh — 3 tickets in the last hour"
- "T1 SLA is at 4h response for the new tier — we need an on-call rotation update"
- "user feedback this week: overwhelming positive on the streaming UX, ask for read receipts"
- "escalation: enterprise customer can't add members to threads — blocking their pilot"
- "reminder: support holiday coverage starts next Monday, who's available?"

**Commit each:**

```bash
git add yard/examples/rfnry-chat/team-communication/client-python-b/
git commit -m "feat(team-communication): add agent-b (Release Coordinator)"
git add yard/examples/rfnry-chat/team-communication/client-python-c/
git commit -m "feat(team-communication): add agent-c (Support Liaison)"
```

---

### Task 6.8: Manual smoke test — all three agents

Start server + 3 agents in 4 terminals. Hit each agent's `/ping-channel` and `/ping-direct` from curl. Verify streaming arrives and personas read distinctly. Fix any prompt issues (often: model adds "Hi <name>!" as a greeting → tighten the prompt).

---

## Phase 7 — Example: React client (`yard/examples/rfnry-chat/team-communication/client-react`)

### Task 7.1: Scaffold from `multi-tenant/client-react`

```bash
cp -r yard/examples/rfnry-chat/multi-tenant/client-react \
      yard/examples/rfnry-chat/team-communication/client-react
# strip node_modules, package-lock.json, .vite cache
```

Edit `package.json`: rename. Update `@rfnry/chat-client-react` to point at the locally-built version of the new presence-aware library (file: dependency or workspace link).

`npm install`. Verify `npm run typecheck` is clean.

**Commit.**

---

### Task 7.2: Identity + agents.ts (webhook map)

**Files:**
- Modify: `client-react/src/app.tsx` (identity carries `tenant: {channel: "*"}`)
- Create: `client-react/src/agents.ts`

```typescript
// agents.ts
export type AgentSpec = {
  id: string
  name: string
  webhookUrl: string
}

export const AGENTS: AgentSpec[] = [
  { id: 'agent-a', name: 'Agent A', webhookUrl: 'http://localhost:9100' },
  { id: 'agent-b', name: 'Agent B', webhookUrl: 'http://localhost:9101' },
  { id: 'agent-c', name: 'Agent C', webhookUrl: 'http://localhost:9102' },
]

export function webhookFor(agentId: string): string | null {
  return AGENTS.find((a) => a.id === agentId)?.webhookUrl ?? null
}
```

In `app.tsx`, drop the multi-tenant org/workspace selectors. Identity carries `tenant: { channel: '*' }`. Persist guest in `sessionStorage` (same `multi-tenant` pattern).

**Commit.**

---

### Task 7.3: Sidebar — Channels + Users + Assistants sections

**Files:**
- Modify: `client-react/src/sidebar.tsx`
- Create: `client-react/src/dm.ts` — utility for stable DM thread IDs

```typescript
// dm.ts
export function dmThreadId(a: string, b: string): string {
  return 'dm_' + [a, b].sort().join('__')
}
```

Sidebar replaces the multi-tenant version with three sections:

```tsx
const channels = useThreads().data?.items.filter((t) => t.metadata.kind === 'channel') ?? []
const presence = usePresence()
const otherUsers = presence.byRole.user.filter((u) => u.id !== identity.id)
const assistants = presence.byRole.assistant
```

Each section is a list of buttons; click handlers:
- Channel → `onPickThread(channel.id)`.
- User / Assistant → `openOrCreateDm(other)`:
  ```typescript
  const dmId = dmThreadId(identity.id, other.id)
  const existing = await client.rest.getThread(dmId).catch(() => null)
  if (!existing) {
    await createThread({
      id: dmId,
      tenant: {},
      metadata: { kind: 'dm' },
      clientId: crypto.randomUUID(),
    })
    await client.addMember(dmId, other)
  }
  onPickThread(dmId)
  ```

> Verify `createThread` accepts an explicit `id`. If not, use the server-generated id and store the mapping client-side, OR add a tiny `getOrCreateDm` helper on the example server that takes both participants and returns a stable id.

**Commit.**

---

### Task 7.4: TopControl

**Files:**
- Create: `client-react/src/top-control.tsx`

```tsx
export function TopControl({ identity }: { identity: UserIdentity }) {
  const presence = usePresence()
  const channels = useThreads().data?.items.filter((t) => t.metadata.kind === 'channel') ?? []

  const onlineAgents = presence.byRole.assistant
  const [agentId, setAgentId] = useState(onlineAgents[0]?.id ?? '')
  const [channelId, setChannelId] = useState(channels[0]?.id ?? '')
  const [busy, setBusy] = useState<null | 'channel' | 'direct'>(null)

  const pingChannel = async () => {
    const url = webhookFor(agentId); if (!url || !channelId) return
    setBusy('channel')
    try {
      await fetch(`${url}/ping-channel`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          channel_id: channelId,
          requested_by: { id: identity.id, name: identity.name },
        }),
      })
    } finally { setBusy(null) }
  }

  const pingDirect = async () => {
    const url = webhookFor(agentId); if (!url) return
    setBusy('direct')
    try {
      await fetch(`${url}/ping-direct`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          user_id: identity.id,
          user_name: identity.name,
          requested_by: { id: identity.id, name: identity.name },
        }),
      })
    } finally { setBusy(null) }
  }

  return (
    <section className="border border-neutral-800 p-3 flex items-center gap-2 text-xs">
      <label>Agent:</label>
      <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
        {onlineAgents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>
      <label>Channel:</label>
      <select value={channelId} onChange={(e) => setChannelId(e.target.value)}>
        {channels.map((c) => <option key={c.id} value={c.id}>#{c.metadata.label}</option>)}
      </select>
      <button onClick={pingChannel} disabled={!agentId || !channelId || busy !== null}>
        {busy === 'channel' ? 'pinging…' : 'Ping in channel'}
      </button>
      <button onClick={pingDirect} disabled={!agentId || busy !== null}>
        {busy === 'direct' ? 'pinging…' : 'Ping me direct'}
      </button>
    </section>
  )
}
```

Mount `<TopControl />` in `app.tsx` above the grid.

**Commit.**

---

### Task 7.5: ThreadPanel header (channel vs DM label)

**Files:**
- Modify: `client-react/src/thread-panel.tsx`

Add a header that derives label from `thread.metadata.kind`:

```tsx
const thread = useThread(threadId)
const headerLabel = thread?.metadata.kind === 'channel'
  ? `# ${thread.metadata.label ?? thread.id}`
  : thread?.metadata.kind === 'dm'
    ? `DM with ${otherMemberName(thread, identity.id)}`
    : thread?.id
```

`onThreadInvited` in `<ChatProvider>` auto-opens the freshly-pinged DM (already wired by stock-assistant pattern).

**Commit.**

---

### Task 7.6: README + manual verification checklist

**Files:**
- Create: `team-communication/README.md` — top-level
- Create: `team-communication/client-react/README.md`

Top-level README mirrors `multi-tenant/README.md`: short intro, layout, the model (channels via tenant, DMs via membership, presence via `usePresence`), `Run` instructions for 5 terminals, and the **manual verification checklist** from the design doc:

1. Start server + 3 agents + frontend.
2. Open 2 tabs → each shows the other in Users.
3. Close a tab → the other tab updates within ~socket-disconnect latency.
4. Send a message in #general from tab A → tab B sees it.
5. Click another user in tab A → DM opens, invisible to tab B.
6. TopControl: pick Agent B + #general → "Ping in channel" → streamed @-mention message appears for everyone.
7. TopControl: pick Agent C → "Ping me direct" → DM auto-opens with streaming.

**Commit.**

---

## End-to-end verification

After all phases:

```bash
# Terminal 1 — server
cd yard/examples/rfnry-chat/team-communication/server-python && uv run poe dev

# Terminal 2-4 — agents
cd ../client-python-a && uv run poe dev    # :9100
cd ../client-python-b && uv run poe dev    # :9101
cd ../client-python-c && uv run poe dev    # :9102

# Terminal 5 — frontend
cd ../client-react && npm install && npm run dev   # :5173

# Open http://localhost:5173 in 2-3 incognito windows.
```

Walk the 7-step checklist. Fix anything that doesn't behave; small drift is normal in the example layer.

---

## Out of scope (defer to follow-up plans)

- Postgres-backed presence (cross-replica sync via redis pub/sub).
- `presence:left` debouncing on reconnect.
- Per-thread visibility predicate in the library's `list_threads` (would let us drop the example's custom filter).
- Typing indicators, read receipts, reactions.
- Recording proactive ping events as `Run` lifecycle in a way the UI surfaces (a "Agent A is typing…" affordance during the stream is *implicit* in the library's stream:start frame today; an explicit indicator could be added).
