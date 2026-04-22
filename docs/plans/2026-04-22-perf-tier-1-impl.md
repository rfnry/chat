# Perf Tier 1 — Streaming hot path, DoS plugs, reconnect hardening — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land the 10 quick-win performance fixes (R1–R10) from `.tresor/profile-2026-04-22/final-performance-report.md` that together unblock the streaming hot path on all three layers, plug two DoS vectors, and remove the reconnect-storm risk.

**Architecture:** Each task is independent (intentionally — Tier 1 was selected for that property). No shared abstractions are introduced. Touch points are localized: 4 files in `server-python`, 4 files in `client-python`, 4 files in `client-react`. The two paired changes (R1 server-side + R2 client-side; R8 selectors + R9 setters) ship together so behavior stays consistent across packages.

**Tech Stack:** unchanged — FastAPI + python-socketio + asyncpg (server), python-socketio + httpx (Python client), React 19 + zustand + socket.io-client (React client).

**Out of scope:** R11 (tenant rooms — needs design), R12 (run API break — needs versioning decision), R13–R26 (Tier 2/3, defer to a follow-up plan). This plan is ~1 day of focused work; do not let it grow.

**Source reports** (for context — read `.tresor/profile-2026-04-22/final-performance-report.md` first):
- `phase-1-react.md` — React findings
- `phase-1-server.md` — Python server findings
- `phase-1-client.md` — Python client findings

---

## Conventions for this plan

- **Worktree:** Implementation should happen in a worktree (e.g. `git worktree add ../chat-perf-tier-1 -b perf/tier-1-streaming`). The plan itself lives on `main` because it's documentation.
- **Commits:** One commit per task (numbered T1..T10 below). Use the existing message style (`fix:`, `perf:`, etc. — lowercase, scoped). Look at recent commits for the exact tone.
- **Tests:** Each task ships with a regression test that proves the *behavioral* change. Performance is verified by inspection of the diff and (optionally) by manual streaming through the dev fixtures — no benchmark suite is part of this plan, per the user's choice.
- **Test runners:** From the relevant package directory:
  - `uv run pytest tests/path/test_x.py::test_name -xvs` for Python
  - `npx vitest run tests/path/file.test.ts -t "name"` for React
- **Don't touch other tests.** Existing tests must continue to pass. Run the full suite before each commit (`uv run poe test` or `npm run test`).
- **No CI runs the suite** (per CLAUDE.md). Verify locally.

---

## Task ordering

The audit's `R1..R10` numbering is by topic, not execution order. Execute in this order — easiest standalone fixes first, paired changes together at the end:

| Order | ID | Title | Package |
|---|---|---|---|
| **T1** | R3 | Cap `GET /events?limit` server-side | server-python |
| **T2** | R10 | Replace `JSON.stringify`-based `identitiesEqual` | client-react |
| ~~T3~~ | ~~R5~~ | ~~Move raw-event listener registration into `SocketTransport.__init__`~~ — **WITHDRAWN** (revert `ec0a298`): audit premise was wrong; python-socketio 5.16's `Client.on()` does dict-replace, not accumulate. No production bug exists. |
| **T4** | R6a | Exponential backoff + jitter on Python client `run()` retries | client-python |
| **T5** | R6b | Configure `reconnectionDelayMax` on React client | client-react |
| **T6** | R4 | Disable `permessage-deflate` for Socket.IO | server-python |
| **T7** | R1 + R2 | Cache thread in session for `stream:delta`; switch Python client to fire-and-forget emit | server-python + client-python |
| **T8** | R7 | Replace `addEvent` re-sort with binary-insert | client-react |
| **T9** | R8 + R9 | `useShallow` selectors; remove root-state spreads from setters | client-react |
| **T10** | (verification) | Manual streaming smoke test + full suite green | all |

---

## T1 — Cap `GET /threads/{id}/events?limit` server-side  (R3)

**Why:** A caller passing `limit=1_000_000` triggers a full event-table scan, 1M pydantic constructions, and a single blocking JSON serialization. Trivially exploitable; trivially fixed.

**Files:**
- Modify: `packages/server-python/src/rfnry_chat_server/server/rest/messages.py:54-67`
- Test: `packages/server-python/tests/server/` (find or create the right REST test file — check existing layout)

### Step 1: Find the existing test file for this endpoint

Run: `cd packages/server-python && grep -rn "list_events\|GET.*events\|/events\"" tests/`

Expected: identifies a test file (likely `tests/server/test_rest_messages.py` or similar). If none exists for this exact endpoint, create one alongside the closest sibling.

### Step 2: Write the failing test

Add to the identified test file:

```python
async def test_list_events_caps_limit_at_200(
    client: AsyncClient,  # whatever the test fixture is in this repo
    thread_id: str,
    auth_headers: dict[str, str],
) -> None:
    # Seed > 200 events into the thread first (use existing seeding helper or
    # call the message:send / event:send path in a loop).
    for _ in range(250):
        await server.publish_event(_make_message_event(thread_id), thread=thread)

    resp = await client.get(
        f"/threads/{thread_id}/events?limit=10000",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 200, "limit must be capped server-side"
```

If a similar test already exists with a different limit, copy its fixture wiring. **Don't invent fixtures** — match what's there.

### Step 3: Run the test, verify it fails

Run: `uv run pytest tests/server/test_rest_messages.py::test_list_events_caps_limit_at_200 -xvs`

Expected: FAIL with `assert 250 == 200` (or the seeded count).

### Step 4: Apply the cap

Edit `packages/server-python/src/rfnry_chat_server/server/rest/messages.py`:

```python
# Before (line 54-67):
@router.get("/events", response_model=Page[Event])
async def list_events(
    thread_id: str,
    request: Request,
    limit: int = 100,
    identity: Identity = Depends(resolve_identity),
) -> Page[Event]:
    server = get_server(request)
    thread = await server.store.get_thread(thread_id)
    if thread is None or not matches(thread.tenant, identity_tenant(identity)):
        raise HTTPException(status_code=404, detail="thread not found")
    if not await server.check_authorize(identity, thread_id, "thread.read"):
        raise HTTPException(status_code=403, detail="not authorized: thread.read")
    return await server.store.list_events(thread_id, limit=limit)
```

Change to:

```python
MAX_EVENTS_LIMIT = 200  # module-level, above build_router

# Inside list_events:
return await server.store.list_events(thread_id, limit=min(limit, MAX_EVENTS_LIMIT))
```

Use FastAPI's `Query(100, le=MAX_EVENTS_LIMIT)` instead if you want a 422 on out-of-range — discuss with reviewer; the silent-cap is friendlier for existing callers and matches what most chat APIs do.

### Step 5: Run the test, verify it passes

Run: `uv run pytest tests/server/test_rest_messages.py::test_list_events_caps_limit_at_200 -xvs`

Expected: PASS.

### Step 6: Run full server test suite

Run: `uv run poe test`

Expected: all green. If anything else broke, the cap is wrong — investigate.

### Step 7: Commit

```bash
git add packages/server-python/src/rfnry_chat_server/server/rest/messages.py packages/server-python/tests/server/
git commit -m "fix(server): cap GET /threads/{id}/events?limit at 200 to prevent unbounded reads"
```

---

## T2 — Replace `JSON.stringify`-based `identitiesEqual`  (R10)

**Why:** `JSON.stringify` runs on every `ChatProvider` render, walking unbounded `metadata` payloads. Identity equality only needs scalar fields.

**Files:**
- Modify: `packages/client-react/src/provider/ChatProvider.tsx:40-44`
- Test: `packages/client-react/tests/provider/` (find or create)

### Step 1: Locate test file

Run: `cd packages/client-react && ls tests/provider/`

If a test exists, add to it. If not, create `tests/provider/identitiesEqual.test.ts` (export the function for testing — see Step 4).

### Step 2: Write the failing test

```ts
import { describe, it, expect } from 'vitest'
import { identitiesEqual } from '../../src/provider/ChatProvider'  // export needed

describe('identitiesEqual', () => {
  it('returns true for the same id+role+name even when metadata differs', () => {
    const a = { id: 'u_1', role: 'user', name: 'Alice', metadata: { foo: 'x' } }
    const b = { id: 'u_1', role: 'user', name: 'Alice', metadata: { foo: 'y' } }
    expect(identitiesEqual(a as never, b as never)).toBe(true)
  })

  it('returns false when id differs', () => {
    const a = { id: 'u_1', role: 'user', name: 'Alice', metadata: {} }
    const b = { id: 'u_2', role: 'user', name: 'Alice', metadata: {} }
    expect(identitiesEqual(a as never, b as never)).toBe(false)
  })

  it('returns false when role differs (e.g. user → assistant)', () => {
    const a = { id: 'u_1', role: 'user', name: 'Alice', metadata: {} }
    const b = { id: 'u_1', role: 'assistant', name: 'Alice', metadata: {} }
    expect(identitiesEqual(a as never, b as never)).toBe(false)
  })

  it('handles null/undefined symmetrically', () => {
    expect(identitiesEqual(null, null)).toBe(true)
    expect(identitiesEqual(null, undefined)).toBe(true)
    expect(identitiesEqual(null, { id: 'u_1', role: 'user', name: 'A', metadata: {} } as never)).toBe(false)
  })
})
```

### Step 3: Run the test, verify it fails

Run: `npx vitest run tests/provider/identitiesEqual.test.ts`

Expected: FAIL — either the import fails (function not exported) or the metadata-differs test fails (current implementation calls `JSON.stringify` and would return `false`).

### Step 4: Replace the function and export it

Edit `packages/client-react/src/provider/ChatProvider.tsx`:

```ts
// Before (line 40-44):
function identitiesEqual(a?: Identity | null, b?: Identity | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  return JSON.stringify(a) === JSON.stringify(b)
}

// After:
export function identitiesEqual(a?: Identity | null, b?: Identity | null): boolean {
  if (a === b) return true
  if (a == null || b == null) return a == b  // both null/undefined is equal
  return a.id === b.id && a.role === b.role && a.name === b.name
}
```

`metadata` is intentionally excluded — identity *equality* for the purpose of "do we need to swap the connected client" is about *who* you're connected as (id/role/name), not their associated tenant data. If the consumer changes metadata only, no reconnect is desired.

### Step 5: Run the test, verify it passes

Run: `npx vitest run tests/provider/identitiesEqual.test.ts`

Expected: all 4 cases PASS.

### Step 6: Run full React test suite

Run: `npm run test`

Expected: all green.

### Step 7: Commit

```bash
git add packages/client-react/src/provider/ChatProvider.tsx packages/client-react/tests/provider/identitiesEqual.test.ts
git commit -m "perf(client-react): drop JSON.stringify from identitiesEqual; compare scalar id/role/name"
```

---

## ~~T3~~ — WITHDRAWN: Move raw-event listener registration into `SocketTransport.__init__`  (R5)

**Status: Withdrawn 2026-04-22 (revert `ec0a298`).** The audit's premise was wrong. `python-socketio` 5.16's `Client.on()` does dict-replace at `base_client.py:157` (`self.handlers[namespace][event] = handler`) — it does NOT accumulate. The "doubled dispatch" bug doesn't manifest with the stock library. The `_SioClient` Protocol allows accumulating implementers in theory, but no consumer in this codebase uses one. Skipped to avoid carrying code that prevents a non-bug.

The original task is preserved below for historical context.

---



**Why:** `client.py:107-112` calls `self._socket.on_raw_event(name, handler)` five times per `connect()` call. python-socketio's `.on()` *accumulates*; it does not replace. A second `connect()` call doubles every dispatch. `reconnect()` is safe (it builds a new `SocketTransport`), but the bare-`connect()` path is buggy.

**Files:**
- Modify: `packages/client-python/src/rfnry_chat_client/transport/socket.py` (add a register_handlers method, or accept handlers in `__init__`)
- Modify: `packages/client-python/src/rfnry_chat_client/client.py:106-112`
- Test: `packages/client-python/tests/test_socket.py` (or wherever transport tests live)

### Step 1: Decide the API shape

Read both files end-to-end first. The cleanest fix: keep `on_raw_event` as the registration method, but ensure each handler is registered *exactly once per transport instance*. Two viable approaches:

**A) Idempotent registration:** `on_raw_event` tracks the (event, handler) pairs it has seen and no-ops on duplicates.

**B) Move registration to ChatClient construction time:** `ChatClient.__init__` calls `on_raw_event` once; `connect()` doesn't re-register. Each new `SocketTransport` instance built in `reconnect()` needs the same hookup.

**Recommendation: B.** It mirrors the actual lifetime: handlers belong to the transport, not the connect-call. Move the registration block from `connect()` into a private `_attach_handlers()` method called once at construction (and again from inside `reconnect()` after the new transport is built).

### Step 2: Write the failing test

Add to `tests/test_client.py` (or `tests/test_socket.py` — match existing structure):

```python
async def test_connect_called_twice_does_not_duplicate_listeners() -> None:
    """Calling connect() twice on a ChatClient must not register raw event
    listeners twice. Regression for R5: python-socketio .on() accumulates
    listeners; a second connect() previously caused every event to dispatch
    to both copies of every handler."""
    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient()  # from conftest
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=transport,
    )

    await client.connect()
    listeners_after_first = dict(sio.handlers)  # snapshot count per event
    await client.connect()
    listeners_after_second = dict(sio.handlers)

    for event, handlers in listeners_after_second.items():
        assert len(handlers) == len(listeners_after_first[event]), (
            f"event {event!r} accumulated handlers across connect() calls"
        )
```

You'll likely need to extend `FakeSioClient` to track handlers per event as a list (not a dict-overwrite). Inspect `tests/conftest.py` first; if it already does, use it as-is.

### Step 3: Run, verify failure

Run: `uv run pytest tests/test_client.py::test_connect_called_twice_does_not_duplicate_listeners -xvs`

Expected: FAIL — handler count doubles.

### Step 4: Fix the registration

In `transport/socket.py`, change `on_raw_event` to record + dedupe, OR don't change `SocketTransport` at all and instead change `ChatClient`. Simpler approach: change `ChatClient`.

Edit `packages/client-python/src/rfnry_chat_client/client.py`:

```python
# Before (lines 90-93):
        self._dispatcher = Dispatcher(identity=identity, client=self)
        self._inbox = InboxDispatcher(client=self, auto_join=auto_join_on_invite)
        self._frames = FrameDispatcher()

# Add right after construction of dispatcher/inbox/frames:
        self._attach_socket_handlers()

# Replace `connect()` body (currently lines 106-112) with:
    async def connect(self) -> None:
        await self._socket.connect()

# Add new method:
    def _attach_socket_handlers(self) -> None:
        """Register raw event listeners on the current socket transport.
        Called once at construction and again after `reconnect()` swaps in a
        new transport. python-socketio `.on()` accumulates listeners, so we
        must never call this twice for the same transport instance."""
        self._socket.on_raw_event("event", self._dispatcher.feed)
        self._socket.on_raw_event("thread:invited", self._inbox.feed)
        self._socket.on_raw_event("thread:updated", self._frames.feed_thread_updated)
        self._socket.on_raw_event("members:updated", self._frames.feed_members_updated)
        self._socket.on_raw_event("run:updated", self._frames.feed_run_updated)
```

In `reconnect()` (currently calls `await self.connect()` at the end), insert `self._attach_socket_handlers()` *between* building the new `self._socket` and `self.connect()`:

```python
        self._socket = socket_transport or SocketTransport(...)
        self._attach_socket_handlers()  # NEW — handlers belong to the new transport
        await self._socket.connect()    # was: await self.connect()
```

### Step 5: Run the test, verify it passes

Run: `uv run pytest tests/test_client.py::test_connect_called_twice_does_not_duplicate_listeners -xvs`

Expected: PASS.

### Step 6: Run full client suite

Run: `uv run poe test`

Expected: all green. The `reconnect` tests are particularly important — they should still pass (handlers still attached after reconnect, just via the new path).

### Step 7: Commit

```bash
git add packages/client-python/src/rfnry_chat_client/client.py packages/client-python/tests/test_client.py packages/client-python/tests/conftest.py
git commit -m "fix(client-python): attach raw socket handlers once per transport, not per connect() call"
```

---

## T4 — Exponential backoff + jitter on Python client `run()` retries  (R6a)

**Why:** `client.py:178-191` retries with a fixed 0.2 s delay. A fleet of 50 agents behind a server restart all retry in lockstep every 200 ms, sending a thundering herd at the server.

**Files:**
- Modify: `packages/client-python/src/rfnry_chat_client/client.py:170-191`
- Test: `packages/client-python/tests/test_client.py`

### Step 1: Write the failing test

```python
async def test_run_uses_exponential_backoff_with_jitter(monkeypatch) -> None:
    """run() retries must back off exponentially with jitter — not a fixed
    interval. Regression for R6a (thundering-herd risk)."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("rfnry_chat_client.client.asyncio.sleep", fake_sleep)

    me = AssistantIdentity(id="a_me", name="Me")
    sio = FakeSioClient(connect_raises=ConnectionError("nope"))
    client = ChatClient(
        base_url="http://chat.test",
        identity=me,
        http_client=httpx.AsyncClient(),
        socket_transport=SocketTransport(base_url="http://chat.test", sio_client=sio),
    )

    with pytest.raises(ConnectionError):
        await client.run(connect_retries=6, connect_backoff_seconds=0.1, max_backoff_seconds=2.0)

    # 6 retries → 5 sleeps. Each later sleep should generally be larger than
    # the one before it (jitter can dip slightly, but the trend is up).
    assert len(sleeps) == 5
    assert sleeps[-1] > sleeps[0], f"backoff did not grow: {sleeps}"
    assert max(sleeps) <= 2.0 * 1.5, f"jitter exceeded ceiling: {sleeps}"  # +50% jitter cap
    assert min(sleeps) >= 0.05, f"jitter dropped too low: {sleeps}"  # -50% jitter floor
```

`FakeSioClient` may need a `connect_raises` option — extend it if needed (small change in conftest).

### Step 2: Run, verify failure

Run: `uv run pytest tests/test_client.py::test_run_uses_exponential_backoff_with_jitter -xvs`

Expected: FAIL — `max_backoff_seconds` is not yet a parameter, AND the sleeps are all 0.1.

### Step 3: Implement exponential backoff + jitter

Edit `packages/client-python/src/rfnry_chat_client/client.py`:

```python
import random  # add to imports

# Replace the run() method's retry loop:
    async def run(
        self,
        *,
        connect_retries: int = 50,
        connect_backoff_seconds: float = 0.2,
        max_backoff_seconds: float = 30.0,
        on_connect: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        last_error: BaseException | None = None
        for attempt in range(1, connect_retries + 1):
            try:
                await self.connect()
                _log.info("connected on attempt=%d", attempt)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                _log.debug("connect retry=%d: %s", attempt, exc)
                if attempt < connect_retries:
                    base = min(
                        connect_backoff_seconds * (2 ** (attempt - 1)),
                        max_backoff_seconds,
                    )
                    # Full jitter in [0.5 * base, 1.5 * base] — keeps growth
                    # while breaking lockstep across a fleet of clients.
                    delay = base * (0.5 + random.random())
                    await asyncio.sleep(delay)
        if last_error is not None:
            raise ConnectionError(
                f"failed to connect after {connect_retries} attempts"
            ) from last_error
        # ... rest of method unchanged
```

Note the `if attempt < connect_retries:` guard — no point sleeping after the last failed attempt before raising.

### Step 4: Run the test, verify it passes

Run: `uv run pytest tests/test_client.py::test_run_uses_exponential_backoff_with_jitter -xvs`

Expected: PASS.

### Step 5: Full suite

Run: `uv run poe test`

Expected: all green. Existing `run()` tests may need adjustment if they assert fixed sleep counts — fix them to match the new behavior, not the other way around.

### Step 6: Commit

```bash
git add packages/client-python/src/rfnry_chat_client/client.py packages/client-python/tests/
git commit -m "perf(client-python): exponential backoff + jitter on run() retries to avoid reconnect storms"
```

---

## T5 — Configure `reconnectionDelayMax` on React client  (R6b)

**Why:** socket.io-client's default `reconnectionDelayMax` is 5 s. After a server restart, all browser tabs concentrate retries in 5 s windows.

**Files:**
- Modify: `packages/client-react/src/transport/socket.ts:31-35`
- Test: `packages/client-react/tests/client/` (find the socket transport test or skip — see Step 1)

### Step 1: Decide test approach

socket.io-client doesn't expose its options post-construction in a clean way. Two options:

- **Test the option is passed**: mock `io()` and assert the options object received. Verbose.
- **Skip the test**: this is a one-line config change in a constructor; verify by inspection. The audit cited this exact line.

**Recommendation:** mock `io` and assert the options object — it's worth catching a future regression where someone "simplifies" the config back to defaults.

### Step 2: Write the failing test

In `packages/client-react/tests/client/socketTransport.test.ts` (create if absent):

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'

const ioMock = vi.fn()
vi.mock('socket.io-client', () => ({
  io: (...args: unknown[]) => {
    ioMock(...args)
    return {
      once: (event: string, cb: () => void) => {
        if (event === 'connect') queueMicrotask(cb)
      },
      on: vi.fn(),
      off: vi.fn(),
      disconnect: vi.fn(),
    }
  },
}))

import { SocketTransport } from '../../src/transport/socket'

beforeEach(() => ioMock.mockClear())

describe('SocketTransport.connect', () => {
  it('passes reconnectionDelayMax to socket.io-client to avoid herd retries', async () => {
    const t = new SocketTransport({ baseUrl: 'http://chat.test' })
    await t.connect()
    expect(ioMock).toHaveBeenCalledTimes(1)
    const opts = ioMock.mock.calls[0][1] as Record<string, unknown>
    expect(opts.reconnectionDelayMax).toBeGreaterThanOrEqual(30000)
  })
})
```

### Step 3: Run, verify failure

Run: `npx vitest run tests/client/socketTransport.test.ts`

Expected: FAIL — `opts.reconnectionDelayMax` is `undefined`.

### Step 4: Set the option

Edit `packages/client-react/src/transport/socket.ts`:

```ts
// Before (line 31-35):
    const socket = io(this.baseUrl, {
      path: this.socketPath,
      transports: ['websocket'],
      auth,
    })

// After:
    const socket = io(this.baseUrl, {
      path: this.socketPath,
      transports: ['websocket'],
      auth,
      reconnectionDelayMax: 30_000,  // default 5s; widen to spread reconnect herds
      randomizationFactor: 0.5,       // default; explicit so reviewers see jitter is on
    })
```

### Step 5: Run the test

Run: `npx vitest run tests/client/socketTransport.test.ts`

Expected: PASS.

### Step 6: Full suite

Run: `npm run test`

Expected: all green.

### Step 7: Commit

```bash
git add packages/client-react/src/transport/socket.ts packages/client-react/tests/client/
git commit -m "perf(client-react): widen reconnectionDelayMax to 30s to spread reconnect herds"
```

---

## T6 — Disable `permessage-deflate` for Socket.IO  (R4)

**Resolved 2026-04-22 via README docs (commit `6d15c42`)**, not code. The audit's R4 finding is real (compression IS on by default and adds CPU per stream:delta) but the fix location was wrong: `socketio.AsyncServer` doesn't have a `compression` parameter for WebSocket — only `http_compression` for HTTP polling. WebSocket `permessage-deflate` is controlled by **uvicorn** (`ws_per_message_deflate`, defaults to `True` per `uvicorn/config.py:193`), which the library can't override. The README now recommends `ws_per_message_deflate=False` for streaming-dominant deployments.

The original task description is preserved below for historical context.

---



**Why:** Default `permessage-deflate` compression on a `stream:delta` of ~50 bytes wastes CPU with near-zero compression benefit. Larger frames (history replay) are JSON-already-compressible but those are infrequent.

**Files:**
- Modify: `packages/server-python/src/rfnry_chat_server/socketio/server.py:510-517`
- Test: same file's tests directory

### Step 1: Write the failing test

```python
def test_async_server_disables_compression() -> None:
    """Regression for R4: permessage-deflate adds CPU overhead per
    stream:delta frame with near-zero benefit on tiny payloads."""
    from rfnry_chat_server.socketio.server import ChatSocketIO
    server = _build_minimal_chat_server()  # use existing test helper
    sio_wrapper = ChatSocketIO(server)
    # python-socketio stores compression setting on the underlying engineio
    # server. Inspect the eio attribute.
    assert sio_wrapper.sio.eio.compression is False, (
        "permessage-deflate should be off; tiny stream:delta frames don't compress"
    )
```

If the existing test infra has a different way to inspect the AsyncServer, match it. Look at `tests/socketio/test_thread_namespace_dispatch.py` for how the server is constructed in tests.

### Step 2: Run, verify failure

Run: `uv run pytest tests/socketio/test_thread_namespace_dispatch.py::test_async_server_disables_compression -xvs`

Expected: FAIL — defaults to `True`.

### Step 3: Configure compression off

Edit `packages/server-python/src/rfnry_chat_server/socketio/server.py:510-517`:

```python
        self._sio = socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins="*",
            namespaces="*" if wildcard else None,
            # permessage-deflate is on by default. Most of our traffic is
            # small high-frequency stream:delta frames (LLM tokens) where
            # compression adds CPU with near-zero size benefit. Larger
            # payloads (history replay) compress fine over HTTP.
            compression=False,
        )
```

If `socketio.AsyncServer` doesn't accept `compression` directly, the option lives on the underlying `engineio.AsyncServer` and is set via `engineio_options`:

```python
            engineio_options={"compression": False},
```

Verify which form the installed python-socketio version accepts — check `pyproject.toml` for the version pin (`python-socketio>=5.16.1`) and the installed lib's `AsyncServer.__init__` signature.

### Step 4: Run the test

Run: `uv run pytest tests/socketio/test_thread_namespace_dispatch.py::test_async_server_disables_compression -xvs`

Expected: PASS.

### Step 5: Full suite

Run: `uv run poe test`

Expected: all green. This is a transport-level change; behavior must be identical, only CPU lower.

### Step 6: Commit

```bash
git add packages/server-python/src/rfnry_chat_server/socketio/server.py packages/server-python/tests/socketio/
git commit -m "perf(server): disable permessage-deflate; tiny stream:delta frames don't benefit from compression"
```

---

## T7 — Cache thread in session for `stream:delta`; switch Python client to fire-and-forget emit  (R1 + R2)

**Why:** This is the headline streaming fix. Server pays 2 DB round-trips per delta (`get_thread` + membership) for data that hasn't changed since `stream:start`. Python client blocks on RTT per delta, capping throughput at ~200 tokens/sec. Both bugs are on the same path; ship them together so `stream:delta` is fully unblocked end-to-end.

**Files:**
- Modify: `packages/server-python/src/rfnry_chat_server/socketio/server.py:439-482` (the three `on_stream_*` handlers)
- Modify: `packages/client-python/src/rfnry_chat_client/transport/socket.py:154-157`
- Test: `packages/server-python/tests/socketio/` and `packages/client-python/tests/test_socket.py`

### Step 1 — Server: write failing test

Add to `tests/socketio/test_thread_namespace_dispatch.py` (or sibling):

```python
async def test_stream_delta_does_not_re_check_access_after_start() -> None:
    """Regression for R1: stream:delta on a stream that already passed
    stream:start must not re-query store.get_thread / authorize."""
    server, store, client = await _build_authenticated_test_client()  # helpers in conftest
    store.calls.clear()  # custom recording store; or wrap with a counter

    await client.emit_with_ack("stream:start", {
        "event_id": "evt_1",
        "thread_id": "t_1",
        "run_id": "run_1",
        "target_type": "message",
        "author": _identity_dump(client.identity),
    })

    get_thread_calls_before = store.calls.count("get_thread")
    for i in range(20):
        await client.emit_with_ack("stream:delta", {
            "event_id": "evt_1",
            "thread_id": "t_1",
            "text": f"token {i}",
        })

    get_thread_calls_after = store.calls.count("get_thread")
    assert get_thread_calls_after - get_thread_calls_before == 0, (
        f"stream:delta hit get_thread {get_thread_calls_after - get_thread_calls_before} times for 20 frames"
    )
```

If `store.calls` doesn't exist, build a minimal `RecordingChatStore` wrapper for tests, or extend `InMemoryChatStore` with a call-counter mixin in `conftest.py` only.

### Step 2 — Server: run, verify failure

Run: `uv run pytest tests/socketio/...::test_stream_delta_does_not_re_check_access_after_start -xvs`

Expected: FAIL — count is 20.

### Step 3 — Server: cache the authorized thread in the Socket.IO session

Edit `packages/server-python/src/rfnry_chat_server/socketio/server.py`:

```python
    async def on_stream_start(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        identity = await _identity(self, sid)
        thread_id = data.get("thread_id")
        if not isinstance(thread_id, str):
            return _error("invalid_request", "thread_id required")
        access = await self._access_check(sid, identity, thread_id, action="stream.send")
        if isinstance(access, dict):
            return access
        try:
            frame = StreamStartFrame.model_validate(data)
        except ValidationError as exc:
            return _error("invalid_request", str(exc))
        # Stash the authorized thread keyed by event_id so subsequent delta/end
        # frames don't re-query the store. Cleared in on_stream_end.
        session = await self.get_session(sid)
        active = session.setdefault("active_streams", {})
        active[frame.event_id] = access
        await self.save_session(sid, session)
        await self._server.broadcast_stream_start(frame, thread=access)
        return {"ok": True}

    async def on_stream_delta(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            frame = StreamDeltaFrame.model_validate(data)
        except ValidationError as exc:
            return _error("invalid_request", str(exc))
        session = await self.get_session(sid)
        thread = session.get("active_streams", {}).get(frame.event_id)
        if thread is None:
            return _error("not_found", "stream not started or already ended")
        await self._server.broadcast_stream_delta(frame, thread=thread)
        return {"ok": True}

    async def on_stream_end(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            frame = StreamEndFrame.model_validate(data)
        except ValidationError as exc:
            return _error("invalid_request", str(exc))
        session = await self.get_session(sid)
        active = session.get("active_streams", {})
        thread = active.pop(frame.event_id, None)
        if thread is None:
            return _error("not_found", "stream not started or already ended")
        await self.save_session(sid, session)
        await self._server.broadcast_stream_end(frame, thread=thread)
        return {"ok": True}
```

**Edge case: disconnect mid-stream.** The session evaporates when the sid disconnects, so cached threads are auto-cleaned. If you want explicit cleanup logging, add it in `on_disconnect`, but functionally it's not required.

**Edge case: membership revoked between start and end.** A user who loses thread membership while streaming will continue streaming until `stream:end`. Acceptable — stream lifetimes are seconds. If this matters, periodically re-validate; out of scope for Tier 1.

### Step 4 — Server: run the test

Run: `uv run pytest tests/socketio/...::test_stream_delta_does_not_re_check_access_after_start -xvs`

Expected: PASS — `get_thread` is called exactly once, in `on_stream_start`.

### Step 5 — Python client: write failing test

Add to `tests/test_socket.py`:

```python
async def test_send_stream_delta_uses_emit_not_call() -> None:
    """Regression for R2: stream:delta must be fire-and-forget. Awaiting an
    ack per token caps streaming throughput at 1/RTT."""
    sio = FakeSioClient()
    transport = SocketTransport(base_url="http://chat.test", sio_client=sio)
    await transport.send_stream_delta({
        "event_id": "evt_1",
        "thread_id": "t_1",
        "text": "hello",
    })
    assert sio.emit_calls == [("stream:delta", {"event_id": "evt_1", "thread_id": "t_1", "text": "hello"})]
    assert sio.call_calls == [], "stream:delta must not block on ack"
```

Extend `FakeSioClient` to track `emit_calls` and `call_calls` separately if it doesn't already.

### Step 6 — Python client: run, verify failure

Run: `uv run pytest tests/test_socket.py::test_send_stream_delta_uses_emit_not_call -xvs`

Expected: FAIL — current code uses `.call`.

### Step 7 — Python client: switch delta to emit

Edit `packages/client-python/src/rfnry_chat_client/transport/socket.py`:

```python
# Before (lines 154-157):
    async def send_stream_delta(self, frame: dict[str, Any]) -> dict[str, Any]:
        reply = await self._sio.call("stream:delta", frame)
        _raise_if_error(reply)
        return reply

# After:
    async def send_stream_delta(self, frame: dict[str, Any]) -> None:
        # Fire-and-forget: token streams must not block on per-frame RTT. The
        # server will return errors via the next stream:end ack if the stream
        # was invalidated mid-flight; treat those as the canonical signal.
        await self._sio.emit("stream:delta", frame)
```

The signature changes from `-> dict[str, Any]` to `-> None`. Update callers — only `Stream.write` in `handler/stream.py:79` calls this. It already discards the return value (`await self._client.socket.send_stream_delta(...)` with no assignment).

### Step 8 — Python client: run the test

Run: `uv run pytest tests/test_socket.py::test_send_stream_delta_uses_emit_not_call -xvs`

Expected: PASS.

### Step 9 — Both packages: full test suites

Run: `cd packages/server-python && uv run poe test && cd ../client-python && uv run poe test`

Expected: all green. The integration tests in `tests/integration/` (Python client) are particularly important — they spin up a real server. If they fail, something's drifted between server and client expectations.

### Step 10 — Commit (single commit, both packages, since they ship together)

```bash
git add packages/server-python/ packages/client-python/
git commit -m "perf(stream): cache thread in socket session; fire-and-forget stream:delta from python client

Server: on_stream_start stashes the authorized thread by event_id; on_stream_delta
and on_stream_end read from the session instead of re-querying the store. Removes
2 DB round-trips per token frame.

Python client: send_stream_delta uses sio.emit instead of sio.call. Token streams
no longer block on per-frame ack RTT (~200 tokens/sec cap at 5ms RTT removed)."
```

---

## T8 — Replace `addEvent` re-sort with binary-insert  (R7)

**Why:** `[...existing, event].sort(compareEvents)` is O(n log n) per call. At 100 stream:delta fps with 200+ stored events, this is thousands of full sorts per stream. Events arrive in order; binary-insert is O(log n).

**Files:**
- Modify: `packages/client-react/src/store/chatStore.ts:46-67`
- Test: `packages/client-react/tests/store/chatStore.test.ts` (already exists)

### Step 1: Read the existing test file

Run: `cd packages/client-react && cat tests/store/chatStore.test.ts | head -80`

Note the patterns it uses for setup. Match them.

### Step 2: Add failing test cases

```ts
import { describe, it, expect } from 'vitest'
import { createChatStore } from '../../src/store/chatStore'

function makeEvent(id: string, threadId: string, createdAt: string) {
  return { id, threadId, createdAt, type: 'message', author: { id: 'u', role: 'user', name: 'u', metadata: {} }, content: [] } as never
}

describe('chatStore.addEvent — sort discipline', () => {
  it('keeps events sorted when appending in order (the streaming hot path)', () => {
    const store = createChatStore()
    const { addEvent } = store.getState().actions
    addEvent(makeEvent('e1', 't1', '2026-01-01T00:00:01Z'))
    addEvent(makeEvent('e2', 't1', '2026-01-01T00:00:02Z'))
    addEvent(makeEvent('e3', 't1', '2026-01-01T00:00:03Z'))
    expect(store.getState().events.t1.map((e) => e.id)).toEqual(['e1', 'e2', 'e3'])
  })

  it('keeps events sorted when an out-of-order event arrives', () => {
    const store = createChatStore()
    const { addEvent } = store.getState().actions
    addEvent(makeEvent('e1', 't1', '2026-01-01T00:00:01Z'))
    addEvent(makeEvent('e3', 't1', '2026-01-01T00:00:03Z'))
    addEvent(makeEvent('e2', 't1', '2026-01-01T00:00:02Z'))
    expect(store.getState().events.t1.map((e) => e.id)).toEqual(['e1', 'e2', 'e3'])
  })

  it('dedupes by id', () => {
    const store = createChatStore()
    const { addEvent } = store.getState().actions
    addEvent(makeEvent('e1', 't1', '2026-01-01T00:00:01Z'))
    addEvent(makeEvent('e1', 't1', '2026-01-01T00:00:01Z'))
    expect(store.getState().events.t1.length).toBe(1)
  })
})
```

### Step 3: Run — these may already pass

Run: `npx vitest run tests/store/chatStore.test.ts`

Expected: most/all of these likely pass already (the current code is *correct*, just slow). The point of these tests is to *guard* the behavior across the optimization. If they all pass on `main`, that's fine — proceed to optimization, then re-run.

### Step 4: Implement binary-insert

Edit `packages/client-react/src/store/chatStore.ts`:

```ts
function compareEvents(a: Event, b: Event): number {
  if (a.createdAt < b.createdAt) return -1
  if (a.createdAt > b.createdAt) return 1
  return a.id.localeCompare(b.id)
}

// Insert `event` into a sorted array at the correct position. O(log n) search
// + O(n) splice. For the streaming hot path (events arrive in order), the
// insert point is always the tail, which Array.push specializes in O(1).
function insertSorted(sorted: Event[], event: Event): Event[] {
  const n = sorted.length
  if (n === 0 || compareEvents(sorted[n - 1], event) <= 0) {
    // Hot path: appending at the end (events arrive ordered).
    return n === 0 ? [event] : [...sorted, event]
  }
  // Out-of-order arrival: binary search for the insert point.
  let lo = 0
  let hi = n
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (compareEvents(sorted[mid], event) <= 0) lo = mid + 1
    else hi = mid
  }
  return [...sorted.slice(0, lo), event, ...sorted.slice(lo)]
}
```

Replace the `addEvent` body (line 46-67):

```ts
      addEvent: (event) =>
        set((state) => {
          const existing = state.events[event.threadId] ?? []
          if (existing.some((e) => e.id === event.id)) return state
          const next = insertSorted(existing, event)
          let activeRuns = state.activeRuns
          if (
            (event.type === 'run.completed' ||
              event.type === 'run.failed' ||
              event.type === 'run.cancelled') &&
            event.runId
          ) {
            const threadRuns = { ...(activeRuns[event.threadId] ?? {}) }
            delete threadRuns[event.runId]
            activeRuns = { ...activeRuns, [event.threadId]: threadRuns }
          }
          // NOTE: do NOT spread state — zustand merges shallowly. Spreading
          // forces a new root object identity which wakes every full-store
          // subscriber. (Addressed across all setters in T9.)
          return {
            events: { ...state.events, [event.threadId]: next },
            activeRuns,
          }
        }),
```

The `existing.some(...)` dedupe scan is also O(n). Acceptable for now; can be replaced with a per-thread `Set<string>` of seen ids if profiling shows it as a hotspot, but premature for this plan.

### Step 5: Run all `chatStore` tests

Run: `npx vitest run tests/store/chatStore.test.ts`

Expected: all green — behavior preserved.

### Step 6: Full suite

Run: `npm run test`

Expected: all green.

### Step 7: Commit

```bash
git add packages/client-react/src/store/chatStore.ts packages/client-react/tests/store/chatStore.test.ts
git commit -m "perf(client-react): binary-insert events instead of full re-sort on every addEvent"
```

---

## T9 — `useShallow` selectors; remove root-state spreads from setters  (R8 + R9)

**Why:** Two interacting issues:
- **R8:** `useThreadEvents` (and siblings) subscribe to the *full store* via `store.subscribe(cb)` and only filter inside the snapshot function. Every `set()` wakes every subscriber.
- **R9:** Every setter does `{ ...state, ... }`, replacing the root object identity. Combined with R8, every `addEvent` for thread A wakes every `useThreadEvents(threadB)` subscriber.

Fixing both together means the streaming hot path no longer pays an O(threads × subscribers) wake-up storm.

**Files:**
- Modify: `packages/client-react/src/store/chatStore.ts` (drop root-state spreads from all setters)
- Modify: `packages/client-react/src/hooks/useThreadEvents.ts`
- Modify: `packages/client-react/src/hooks/useThreadMembers.ts`
- Modify: `packages/client-react/src/hooks/useThreadMetadata.ts`
- Modify: `packages/client-react/src/hooks/useConnectionStatus.ts`
- Modify: `packages/client-react/src/hooks/useThreadActiveRuns.ts` (likely also affected)
- Test: `packages/client-react/tests/hooks/` and `tests/store/chatStore.test.ts`

### Step 1: Drop root-state spreads from chatStore setters

Edit `packages/client-react/src/store/chatStore.ts` — for each setter that returns `{ ...state, foo: ... }`, return `{ foo: ... }` instead. Zustand merges shallowly. Specifically:

- `addEvent` — already adjusted in T8
- `setEventsBulk`, `clearThreadEvents`, `setMembers`, `setThreadMeta`, `upsertRun`, `addJoinedThread`, `removeJoinedThread`, `setConnectionStatus` — all currently spread `...state`. Drop it from each.

Example for `setMembers`:

```ts
// Before:
      setMembers: (threadId, members) =>
        set((state) => ({
          ...state,
          members: { ...state.members, [threadId]: members },
        })),
// After:
      setMembers: (threadId, members) =>
        set((state) => ({
          members: { ...state.members, [threadId]: members },
        })),
```

`reset` is the one exception — it intentionally returns a fresh root: `set(() => ({ ...initialState() }))` is correct (it doesn't take `state`, doesn't spread it).

### Step 2: Switch hooks to scoped subscriptions

Read each hook file. Currently they all use `useSyncExternalStore` over `store.subscribe`. Replace with zustand's `useStore` + `useShallow` for collection returns.

Add to imports of each hook (where applicable):

```ts
import { useStore } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
```

For `useThreadEvents`:

```ts
// Before:
import type { Event } from '@rfnry/chat-protocol'
import { useSyncExternalStore } from 'react'
import { useChatStore } from './useChatClient'

const EMPTY: Event[] = []

export function useThreadEvents(threadId: string | null): Event[] {
  const store = useChatStore()
  return useSyncExternalStore(
    (cb) => store.subscribe(cb),
    () => (threadId ? (store.getState().events[threadId] ?? EMPTY) : EMPTY),
    () => (threadId ? (store.getState().events[threadId] ?? EMPTY) : EMPTY)
  )
}

// After:
import type { Event } from '@rfnry/chat-protocol'
import { useStore } from 'zustand'
import { useChatStore } from './useChatClient'

const EMPTY: Event[] = []

export function useThreadEvents(threadId: string | null): Event[] {
  const store = useChatStore()
  // Subscribe to a stable slice — only re-render when this thread's event
  // array reference changes. Other threads' addEvent calls no longer wake
  // this hook. Reference equality is sufficient because addEvent always
  // returns a new array on append.
  return useStore(store, (state) => (threadId ? (state.events[threadId] ?? EMPTY) : EMPTY))
}
```

For `useThreadMembers`, `useThreadMetadata`, `useConnectionStatus`, `useThreadActiveRuns`: same pattern — `useStore(store, (state) => state.<slice>[threadId])`. For hooks that return a derived object/array (e.g. computing something from multiple slices), wrap the selector with `useShallow`:

```ts
return useStore(store, useShallow((state) => ({
  members: state.members[threadId] ?? EMPTY_MEMBERS,
  joined: state.joinedThreads.has(threadId),
})))
```

**Critical:** if a selector returns a *new* object/array reference on every call (e.g. `Object.values(state.activeRuns[threadId] ?? {})`), zustand will re-render every set without `useShallow`. Apply `useShallow` to *every* selector that derives a new collection.

### Step 3: Write the regression test for cross-thread isolation

Add to `tests/hooks/useThreadEvents.test.tsx` (create if absent):

```tsx
import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useThreadEvents } from '../../src/hooks/useThreadEvents'
// You'll need a wrapper that mounts ChatProvider with a test store. Match
// the pattern from tests/hooks/hooks.integration.test.tsx.

describe('useThreadEvents — subscriber scoping', () => {
  it('does not re-render when an unrelated thread receives an event', async () => {
    const { wrapper, store } = makeTestProvider()
    const renderCount = vi.fn()
    const { rerender } = renderHook(
      () => {
        renderCount()
        return useThreadEvents('t_A')
      },
      { wrapper }
    )
    const baseline = renderCount.mock.calls.length

    act(() => {
      store.getState().actions.addEvent(makeEvent('e1', 't_B', '2026-01-01T00:00:00Z'))
    })

    // Hook should NOT re-render — t_A's slice didn't change.
    expect(renderCount.mock.calls.length).toBe(baseline)
  })
})
```

If `makeTestProvider` doesn't exist as a helper, factor one out from the existing integration test or build inline. **Don't reinvent fixtures** — match the existing test structure.

### Step 4: Run regression test

Run: `npx vitest run tests/hooks/useThreadEvents.test.tsx`

Expected: PASS — wake-up doesn't fire for unrelated threads.

If it fails, the most likely culprit is a setter still doing `{ ...state, ... }`. Audit `chatStore.ts` for any remaining root spread.

### Step 5: Full suite

Run: `npm run test`

Expected: all green.

### Step 6: Commit

```bash
git add packages/client-react/src/store/chatStore.ts packages/client-react/src/hooks/ packages/client-react/tests/
git commit -m "perf(client-react): scoped zustand subscriptions; drop root-state spreads from setters

Replaces useSyncExternalStore(store.subscribe) with useStore(store, selector) in
useThreadEvents and siblings. Combined with dropping the {...state, ...} spread
from every setter, addEvent for thread A no longer wakes useThreadEvents(threadB)
subscribers."
```

---

## T10 — Verification

**Why:** Tier 1 is ten independent fixes. Now confirm the streaming hot path actually works end-to-end with all of them landed.

### Step 1: Full test suites, all packages

Run from each package directory:

```bash
cd packages/server-python && uv run poe dev          # check + typecheck + test
cd ../client-python && uv run poe dev
cd ../client-react && npm run check && npm run typecheck && npm run test
```

Expected: all green across the board.

### Step 2: Build artifacts

```bash
cd packages/server-python && uv run poe build
cd ../client-python && uv run poe build
cd ../client-react && npm run build
```

Expected: artifacts in each `dist/` without warnings.

### Step 3: Manual smoke test — streaming end-to-end

If there's a dev fixture or example app, run a streaming session through it and confirm tokens flow. If there isn't (the `examples/` directory was moved per recent commit `e1255a4 cleaning examples / move to yard`), this step is best-effort.

Minimum verification: write a one-off Python script that connects two clients (one streamer, one observer), the streamer sends 1000 deltas, the observer receives them, total time should be roughly `1000 / token-rate-of-source` rather than `1000 × RTT`.

### Step 4: Git log review

Run: `git log --oneline main..HEAD`

Expected: 9 commits (T7 is one commit covering both R1 and R2; T9 is one commit covering R8+R9). Each scoped, each with a clear `fix(...)`/`perf(...)` prefix.

### Step 5: Open the PR

Use the standard `gh pr create` flow. Title: `perf: tier 1 hot-path fixes (streaming, dos plugs, reconnect)`. Body should reference `.tresor/profile-2026-04-22/final-performance-report.md` as the source and list R1–R10 as covered.

---

## What's deferred to a follow-up plan

These were explicitly out of scope for this plan; they each warrant their own design:

- **R11** Tenant rooms — replaces per-SID broadcast loops with single-room emit. Behavior change at the broadcast layer; needs migration consideration for any consumer relying on the current per-SID semantics.
- **R12** `begin_run` / `end_run` API break — return IDs only, add `get_run(id)` for hydration. Breaks every consumer of the public API. Wait for a major version bump.
- **R13–R26** Tier 2/3 — read the consolidated report. Nothing is urgent; pick them up opportunistically when adjacent code is touched.
