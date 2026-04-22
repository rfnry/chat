# Perf Tier 2 — Tenant rooms + Run API ergonomics — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land the two highest-impact Tier 2 fixes (R11 + R12) from `.tresor/profile-2026-04-22/final-performance-report.md`. R11 replaces O(n) per-SID broadcast loops with O(1) room emits via Socket.IO rooms. R12 cuts public `begin_run`/`end_run` round-trips from 4 hops to 1 by returning IDs instead of hydrated `Run` objects.

**Architecture:**
- **R11 (tenant rooms)**: model lifted from the existing `inbox:<identity_id>` room pattern. Each authenticated socket auto-joins a deterministic `tenant:/path` room on connect. Per-SID broadcast loops become single-room emits. The path component is derived from `derive_namespace_path` so the same logic that defines tenant scoping defines room membership — no new naming convention to maintain.
- **R12 (run API)**: surgical signature change on the Python client. `begin_run` returns `str`, `end_run` returns `None`, new `get_run(id) -> Run` for callers that want hydration. Server-side `create_run` adds `RETURNING` for symmetry (currently irrelevant because `started_at` is set in Python; future-proofs DB-side defaults). This is a hard breaking change — both Python packages bump to **0.2.0**, no compat shim, README streaming example rewritten.

**Tech Stack:** unchanged — FastAPI + python-socketio + asyncpg (server), python-socketio + httpx (Python client). No new dependencies.

**Out of scope:** R13–R18 (smaller Tier 2 — defer to a separate plan or do opportunistically). R19–R26 (Tier 3). Anything unrelated to R11/R12.

**Source reports** (read these first):
- `.tresor/profile-2026-04-22/final-performance-report.md` — R11 in "Tier 2 — Higher-impact structural fixes" table; R12 same.
- `.tresor/profile-2026-04-22/phase-1-server.md` — R11 detailed at "HIGH: `broadcast_thread_created_to_sids` / `broadcast_thread_deleted_to_sids` sequentially await per socket"; R12 at "HIGH: `begin_run` issues 3 serial DB round-trips to create a run, and `create_run` doesn't use RETURNING".
- `.tresor/profile-2026-04-22/phase-1-client.md` — R12 detailed at "CRITICAL: Extra REST GET on every public `begin_run` / `end_run` call".

---

## Conventions for this plan

- **Worktree:** Recommended (`git worktree add ../chat-perf-tier-2 -b perf/tier-2-rooms-runapi`). The Tier 1 work went directly to `main`; this plan is more invasive (deletes code, bumps versions) and benefits from PR review in isolation. The plan itself lives on `main` since it's documentation.
- **Branch + PR**: Single branch, single PR — both R11 and R12 ship together (per design decision: shared 0.2.0 release, consumer migrates once).
- **Commits:** One logical commit per task (T1–T6). Version bump (T7) is a single chore commit at the end so the diff is unambiguous when squashed.
- **Tests:** Each task ships with regression coverage. The R11 test that matters most is **tenant isolation**: events for tenant A must not reach a socket from tenant B. The R12 test that matters most is the **return-type contract**: `begin_run` returns `str`, not `Run`.
- **Test runners**: From the relevant package directory:
  - `uv run pytest tests/path/test_x.py::test_name -xvs` for Python
- **Don't touch other tests** unless they assert the old behavior (e.g. `assert isinstance(run, Run)` for `begin_run`'s return — those tests need updating to match the new contract, not preserved as-is).

---

## Task ordering

R12 ships first (simpler, isolated to one method per package). R11 ships second (touches more files, deletes code). Version bump and READMEs go at the end so the breaking change is committed atomically.

| Order | ID | Title | Package |
|---|---|---|---|
| **T1** | R12.1 | Server: `create_run` uses `RETURNING` | server-python |
| **T2** | R12.2 | Python client: `begin_run` / `end_run` return IDs; new `get_run(id)` | client-python |
| **T3** | R11.1 | Server: `tenant_room` helper + auto-join in `on_connect` | server-python |
| **T4** | R11.2 | Server: room-based `broadcast_thread_created` / `broadcast_thread_deleted`; delete per-SID code | server-python |
| **T5** | (docs) | Update READMEs (Python client streaming example; server README if relevant) | both |
| **T6** | (release) | Bump both Python packages to **0.2.0** + CHANGELOG entry | both |
| **T7** | (verify) | Final verification + integration suite + manual smoke test | all |

---

## T1 — `create_run` uses `RETURNING`  (R12.1)

**Why:** Currently `PostgresChatStore.create_run` does a plain `INSERT` and returns the input `Run` unchanged. It works because `started_at` is set in Python with `datetime.now(UTC)` before insert. But this hides a latent timestamp-drift hazard: any future change that uses a DB-side `DEFAULT now()` would silently desync from what the Python caller sees. `RETURNING` fixes the contract without behavior change today.

**Files:**
- Modify: `packages/server-python/src/rfnry_chat_server/store/postgres/store.py:234-253` (`create_run` method)
- Test: find existing `tests/store/test_postgres_runs.py` (or sibling) — add a contract test

### Step 1: Read the current implementation

Run: `cd packages/server-python && grep -n "create_run\|def create_run" src/rfnry_chat_server/store/postgres/store.py`

Read the method (around line 234). Note that `_row_to_run` exists nearby — use it to convert the RETURNING row.

### Step 2: Write the failing test

Add to `tests/store/test_postgres_runs.py`:

```python
async def test_create_run_returns_persisted_state_via_returning(clean_db: asyncpg.Pool) -> None:
    """Regression for R12.1: create_run must reflect the persisted DB state,
    not just the input. Today started_at is set in Python so input == output;
    this test pins the contract for future schema changes that might use
    DB-side defaults."""
    store = PostgresChatStore(pool=clean_db)
    # Seed a thread first
    thread = await store.create_thread(...)  # match existing test patterns
    actor = AssistantIdentity(id="a_x", name="X")

    run = Run(
        id=f"run_{secrets.token_hex(8)}",
        thread_id=thread.id,
        actor=actor,
        triggered_by=actor,
        status="running",
        started_at=datetime.now(UTC),
    )
    created = await store.create_run(run)

    # The returned object must come from the DB row (proven by re-fetching
    # and checking field-for-field equality).
    refetched = await store.get_run(run.id)
    assert refetched is not None
    assert created.model_dump(mode="json") == refetched.model_dump(mode="json"), (
        "create_run's return value must equal what get_run reads back"
    )
```

Use existing fixtures from `tests/store/conftest.py` — match patterns from `test_postgres_runs.py`'s existing tests.

### Step 3: Run, verify pass on current code

Run: `cd packages/server-python && uv run pytest tests/store/test_postgres_runs.py::test_create_run_returns_persisted_state_via_returning -xvs`

Expected: PASS even on current code, because `started_at` is set in Python and the persisted row matches. **This is a contract pin, not a regression test against a current bug.** The test value is forward-protective.

### Step 4: Apply RETURNING

Edit `packages/server-python/src/rfnry_chat_server/store/postgres/store.py`:

```python
async def create_run(self, run: Run) -> Run:
    async with self._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO runs (id, thread_id, actor, triggered_by, status,
                              error, idempotency_key, metadata, started_at, completed_at)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6::jsonb, $7, $8::jsonb, $9, $10)
            RETURNING id, thread_id, actor, triggered_by, status, error,
                      idempotency_key, metadata, started_at, completed_at
            """,
            run.id,
            run.thread_id,
            json.dumps(run.actor.model_dump(mode="json")),
            json.dumps(run.triggered_by.model_dump(mode="json")),
            run.status,
            json.dumps(run.error.model_dump(mode="json")) if run.error else None,
            run.idempotency_key,
            json.dumps(run.metadata),
            run.started_at,
            run.completed_at,
        )
    assert row is not None  # INSERT ... RETURNING always returns a row
    return _row_to_run(row)
```

### Step 5: Run the test

Run: `cd packages/server-python && uv run pytest tests/store/test_postgres_runs.py -xvs`

Expected: all tests PASS (existing + new).

### Step 6: Full server suite + lint + typecheck

Run: `cd packages/server-python && uv run poe dev`

Expected: all green.

### Step 7: Commit

```bash
git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/src/rfnry_chat_server/store/postgres/store.py packages/server-python/tests/store/test_postgres_runs.py
git -C /home/frndvrgs/software/rfnry/chat commit -m "fix(server): create_run uses RETURNING to reflect persisted state"
```

---

## T2 — Python client: `begin_run` / `end_run` return IDs; new `get_run(id)`  (R12.2)

**Why:** The current `begin_run` does a socket call **plus** a REST GET to hydrate the `Run` object — 2 sequential network hops. `end_run` does the same. A consumer following the manual-streaming README pattern pays 4 sequential hops per emitter handler invocation. The dispatcher's internal path (`_run_emitter`) already calls `socket.begin_run` directly and skips the REST GET, so the cost is borne entirely by external consumers.

This is a **breaking change** to the public API. No compat shim per project policy. Both Python packages will bump to 0.2.0 in T6.

**Files:**
- Modify: `packages/client-python/src/rfnry_chat_client/client.py:240-264` (`begin_run`, `end_run`)
- Modify: `packages/client-python/src/rfnry_chat_client/client.py` (add `get_run` method — see Step 4)
- Test: `packages/client-python/tests/test_run.py` (existing — assertions need updating)

### Step 1: Read the current implementation and tests

Run:
```bash
cd packages/client-python
grep -n "def begin_run\|def end_run\|def get_run" src/rfnry_chat_client/client.py
grep -n "begin_run\|end_run" tests/test_run.py
```

Note every test that asserts `isinstance(result, Run)` or accesses `.id`/`.status` on the return value of `begin_run`/`end_run`. Each will need updating.

### Step 2: Write the failing tests

Add to `tests/test_run.py`:

```python
async def test_begin_run_returns_run_id_string() -> None:
    """R12.2: begin_run returns the run_id as a string, not a hydrated Run.
    Saves the extra REST GET previously needed for hydration."""
    sio = FakeSioClient()
    sio.ack_replies["run:begin"] = {"run_id": "run_abc", "status": "running"}
    client = _make_test_client(sio=sio)  # match existing helper

    result = await client.begin_run("t_1", triggered_by_event_id="evt_1")
    assert result == "run_abc", f"expected str run_id, got {result!r}"
    assert isinstance(result, str), f"expected str, got {type(result).__name__}"


async def test_end_run_returns_none() -> None:
    """R12.2: end_run returns None (was: hydrated Run via extra REST GET)."""
    sio = FakeSioClient()
    sio.ack_replies["run:end"] = {"run_id": "run_abc", "status": "completed"}
    client = _make_test_client(sio=sio)

    result = await client.end_run("run_abc")
    assert result is None, f"expected None, got {result!r}"


async def test_get_run_returns_hydrated_run() -> None:
    """R12.2: callers that need the full Run object call get_run(id)
    explicitly. This is the only path that pays the REST GET cost."""
    # Use the existing httpx mock pattern from tests/test_rest.py
    # Mock GET /chat/runs/run_abc to return a Run JSON.
    # Then assert client.get_run("run_abc") returns a properly-typed Run.
    ...
```

Match the existing test fixtures and helpers (`_make_test_client`, FakeSioClient ack patterns, httpx mocking style).

### Step 3: Run, verify failure

Run: `cd packages/client-python && uv run pytest tests/test_run.py -xvs -k "returns_run_id_string or returns_none or returns_hydrated_run"`

Expected: tests FAIL (current code returns `Run` from `begin_run`/`end_run` and there's no `get_run` method).

### Step 4: Implement the new signatures

Edit `packages/client-python/src/rfnry_chat_client/client.py`. Replace `begin_run` and `end_run`, add `get_run`:

```python
async def begin_run(
    self,
    thread_id: str,
    *,
    triggered_by_event_id: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    """Open a Run and return its id. Use `get_run(id)` to fetch the full
    Run object if needed."""
    reply = await self._socket.begin_run(
        thread_id,
        triggered_by_event_id=triggered_by_event_id,
        idempotency_key=idempotency_key,
    )
    return reply["run_id"]

async def end_run(
    self,
    run_id: str,
    *,
    error: RunError | None = None,
) -> None:
    """Close a Run. Use `get_run(id)` afterward if you need the final state."""
    payload: dict[str, Any] | None = None
    if error is not None:
        payload = {"code": error.code, "message": error.message}
    await self._socket.end_run(run_id, error=payload)

async def get_run(self, run_id: str) -> Run:
    """Fetch the current state of a Run by id."""
    return await self._rest.get_run(run_id)
```

### Step 5: Update the dispatcher's internal `_run_emitter` path

Run: `grep -n "begin_run\|end_run" src/rfnry_chat_client/dispatch.py`

Find any internal usage. The dispatcher already calls `self._client.socket.begin_run()` directly (the transport-level method, not the public ChatClient method) — verify this is still the case after the change. If anything calls `self._client.begin_run(...)` and uses the return value, it needs updating.

If the dispatcher's `_run_emitter` was relying on getting back a hydrated `Run` from the public `begin_run`, that's a bug masked by the old API — it never needed hydration. Confirm the dispatcher only needs the `run_id` string.

### Step 6: Update existing tests that assert the old shape

Run:
```bash
cd packages/client-python
grep -rn "begin_run\|end_run" tests/ | grep -v "test_run.py"
```

For every test that does `assert isinstance(result, Run)` or `result.id`/`result.status`, update to either:
- Match the new contract: `assert result == "run_abc"` for `begin_run`, drop assertions for `end_run`
- If the test specifically needed the hydrated Run, add a follow-up `await client.get_run(...)`

The integration tests (`tests/integration/`) are particularly important — they hit a real server and would have asserted the old shape. Update them to match.

### Step 7: Run the new tests + full suite

Run:
```bash
cd packages/client-python
uv run pytest tests/test_run.py -xvs
uv run poe dev
```

Expected: all green.

### Step 8: Commit

```bash
git -C /home/frndvrgs/software/rfnry/chat add packages/client-python/
git -C /home/frndvrgs/software/rfnry/chat commit -m "$(cat <<'EOF'
feat(client-python)!: begin_run/end_run return ids; add get_run(id)

BREAKING CHANGE: ChatClient.begin_run now returns str (the run_id) instead
of a hydrated Run object. ChatClient.end_run now returns None. Callers that
need the full Run object should call client.get_run(run_id) explicitly.

Removes the implicit REST GET that previously hydrated the Run on every
begin_run/end_run call — a manual-streaming handler now pays 1 socket hop
per lifecycle event instead of 2 socket+REST hops.
EOF
)"
```

The `!` after `feat(client-python)` and the `BREAKING CHANGE:` footer are conventional-commits semver signals — they're what tooling reads to determine the version bump. The actual version bump happens in T6.

---

## T3 — Server: `tenant_room` helper + auto-join in `on_connect`  (R11.1)

**Why:** First half of R11. Add the room infrastructure without changing any broadcast behavior yet. T4 will swap callers over and delete the old per-SID code. Splitting lets each commit be reviewable in isolation and keeps the working tree green between commits.

**Files:**
- Modify: `packages/server-python/src/rfnry_chat_server/socketio/server.py` (add helper, call `enter_room` in `on_connect`)
- Test: `packages/server-python/tests/socketio/` — verify rooms are joined correctly

### Step 1: Read the current `on_connect` flow

Read `packages/server-python/src/rfnry_chat_server/socketio/server.py:175-220`. Note:
- `inbox:<identity_id>` room is already joined in both branches (with and without `namespace_keys`)
- `_sid_identities[sid] = identity` populates the dict that `_collect_tenant_targets` later scans
- `parse_namespace_path` extracts the tenant dict from the concrete namespace
- `derive_namespace_path` is the inverse — we'll use it to compute the room name

### Step 2: Define the room name format

The room name should be deterministic across processes (so any worker can emit to it) and reuse existing namespace logic. Format:

```python
def _tenant_room(tenant: dict[str, str], namespace_keys: list[str] | None) -> str:
    """Deterministic room name for a tenant scope. Reuses derive_namespace_path
    so the same logic that defines tenant scoping defines room membership."""
    path = derive_namespace_path(tenant, namespace_keys=namespace_keys)
    return f"tenant:{path}"  # e.g. "tenant:/", "tenant:/acme", "tenant:/acme/ws_42"
```

For single-tenant deployments (`namespace_keys=None`), the room name is `tenant:/` — a sentinel that all sockets join, equivalent to the old "match every SID" behavior.

Place this helper at module level near `thread_room` and `_inbox_room` (in `socketio/server.py` if it lives there, or `broadcast/socketio.py` — match the location of similar helpers; `broadcast/socketio.py:16-21` has `_thread_room` and `_inbox_room` so put `_tenant_room` there for symmetry).

### Step 3: Write the failing test

Add to a sensible test file (likely `tests/socketio/test_thread_namespace_dispatch.py` or a new `test_tenant_room.py`):

```python
async def test_authenticated_socket_joins_tenant_room_on_connect() -> None:
    """R11.1: every authenticated socket auto-joins a tenant room derived from
    its identity tenant. This is the foundation for R11.2 (replacing per-SID
    broadcast loops with single-room emits)."""
    server, sio_app = await _build_test_server(namespace_keys=["org"])
    identity = UserIdentity(id="u_1", name="A", metadata={"tenant": {"org": "acme"}})
    sid = await _connect_authenticated_socket(sio_app, identity, namespace="/acme")

    # The exact mechanism for asserting room membership depends on
    # python-socketio internals; the simplest check: emit to the tenant room
    # and assert the socket received it.
    await sio_app.emit("test:ping", {"hello": "world"}, room="tenant:/acme")
    # Then assert the test socket received the frame (using whatever
    # collector pattern existing tests use).
```

Match existing test patterns in `tests/socketio/`. If there's a "send + receive" helper, use it.

### Step 4: Run, verify failure

Run: `cd packages/server-python && uv run pytest tests/socketio/...::test_authenticated_socket_joins_tenant_room_on_connect -xvs`

Expected: FAIL — the room emit lands nowhere because no socket has joined `tenant:/acme`.

### Step 5: Implement `_tenant_room` and join in `on_connect`

In `broadcast/socketio.py` (where the other `_..._room` helpers live):

```python
def _tenant_room(tenant: dict[str, str], namespace_keys: list[str] | None) -> str:
    from rfnry_chat_server.server.namespace import derive_namespace_path
    path = derive_namespace_path(tenant, namespace_keys=namespace_keys)
    return f"tenant:{path}"
```

(Or import at module top if there's no circular-import concern.)

In `socketio/server.py` `on_connect`, after `self._sid_identities[sid] = identity` (around line 213), add:

```python
# Join the tenant room so per-tenant broadcasts (thread:created,
# thread:deleted) can fan out via a single sio.emit(room=...) instead of
# scanning every connected SID. The room name is deterministic across
# workers; an empty namespace_keys deployment lands everyone in tenant:/.
identity_tenant = _identity_tenant(identity)
ns_keys = self._server.namespace_keys
try:
    tenant_room_name = _tenant_room(identity_tenant, namespace_keys=ns_keys)
except NamespaceViolation:
    # Identity tenant doesn't satisfy namespace_keys — auth above should
    # have caught this, but defend defensively.
    raise socketio.exceptions.ConnectionRefusedError("namespace_invalid: tenant room")
await self.enter_room(sid, tenant_room_name)
```

Place this **inside** the `try` block (so a failure cleans up `_sid_namespaces` and `_sid_identities`), **after** the existing `enter_room` for inbox.

Add the import: `from rfnry_chat_server.broadcast.socketio import _tenant_room` (or restructure if there's a cleaner place).

### Step 6: Run the test

Run: `cd packages/server-python && uv run pytest tests/socketio/...::test_authenticated_socket_joins_tenant_room_on_connect -xvs`

Expected: PASS.

### Step 7: Full server suite + lint + typecheck

Run: `cd packages/server-python && uv run poe dev`

Expected: all green. No existing test should fail — this is purely additive.

### Step 8: Commit

```bash
git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/
git -C /home/frndvrgs/software/rfnry/chat commit -m "feat(server): authenticated sockets auto-join tenant:<path> room on connect"
```

---

## T4 — Server: room-based broadcast + delete per-SID code  (R11.2)

**Why:** Second half of R11. Switch the per-SID broadcast methods to single-room emits and delete the now-unused scaffolding (`_collect_tenant_targets`, `connected_identities`, `_sid_identities`, the `_to_sids` broadcaster methods).

**Files:**
- Modify: `packages/server-python/src/rfnry_chat_server/broadcast/socketio.py` (add new methods, remove `_to_sids` ones)
- Modify: `packages/server-python/src/rfnry_chat_server/broadcast/protocol.py` (update Protocol)
- Modify: `packages/server-python/src/rfnry_chat_server/broadcast/recording.py` (update test broadcaster)
- Modify: `packages/server-python/src/rfnry_chat_server/server/chat_server.py:280-309` (`publish_thread_created`, `publish_thread_deleted`, delete `_collect_tenant_targets`)
- Modify: `packages/server-python/src/rfnry_chat_server/socketio/server.py:213-235` (delete `_sid_identities` and `connected_identities`)

### Step 1: Write the failing tenant-isolation test

This is the single most important test for R11. Add to `tests/socketio/`:

```python
async def test_thread_created_emits_only_to_matching_tenant_room() -> None:
    """R11.2 (tenant isolation): a thread:created event for tenant A must
    NOT reach a socket from tenant B. The previous per-SID broadcast loop
    enforced this via filtering; the new room-based emit enforces it via
    Socket.IO room membership. This test pins the contract."""
    server, sio_app = await _build_test_server(namespace_keys=["org"])
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "acme"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "globex"}})
    sid_alice = await _connect_authenticated_socket(sio_app, alice, namespace="/acme")
    sid_bob = await _connect_authenticated_socket(sio_app, bob, namespace="/globex")

    # Create a thread in alice's tenant
    thread = Thread(id="t_1", tenant={"org": "acme"}, ...)
    await server.publish_thread_created(thread)

    # Assert alice received thread:created and bob did NOT.
    # Use the recording/collector pattern from existing tests.
    assert _frames_for(sid_alice, "thread:created") == [thread.model_dump(mode="json", by_alias=True)]
    assert _frames_for(sid_bob, "thread:created") == []
```

### Step 2: Run, verify either it passes (current per-SID code is correct) or fails for a setup reason

Run: `cd packages/server-python && uv run pytest tests/socketio/...::test_thread_created_emits_only_to_matching_tenant_room -xvs`

The current per-SID code DOES enforce this isolation (via `_collect_tenant_targets` filtering by `matches(thread.tenant, ...)`), so this test SHOULD pass on current code. **That's correct** — this is a contract pin. The R11 change preserves the contract, just via a different mechanism.

If the test fails for an unrelated reason (helper missing, fixture mismatch), fix the test setup until it passes on current code. Then proceed to the optimization.

### Step 3: Add the new room-based broadcaster methods

Edit `packages/server-python/src/rfnry_chat_server/broadcast/socketio.py`. Add before the old `_to_sids` methods:

```python
async def broadcast_thread_created(
    self,
    thread: Thread,
    *,
    namespace_keys: list[str] | None,
    namespace: str | None = None,
) -> None:
    await self._sio.emit(
        "thread:created",
        thread.model_dump(mode="json", by_alias=True),
        room=_tenant_room(thread.tenant, namespace_keys=namespace_keys),
        namespace=namespace or "/",
    )

async def broadcast_thread_deleted(
    self,
    thread_id: str,
    tenant: dict[str, str],
    *,
    namespace_keys: list[str] | None,
    namespace: str | None = None,
) -> None:
    await self._sio.emit(
        "thread:deleted",
        {"thread_id": thread_id},
        room=_tenant_room(tenant, namespace_keys=namespace_keys),
        namespace=namespace or "/",
    )
```

The `namespace` arg here is the Socket.IO namespace path (`/`, `/acme`, etc.), which under wildcard mode is the concrete tenant namespace. This matches the pattern used by other `broadcast_*` methods in the file.

### Step 4: Update the Broadcaster Protocol

Edit `packages/server-python/src/rfnry_chat_server/broadcast/protocol.py` to add the new methods and remove the `_to_sids` ones. The Protocol should reflect the new contract exactly.

### Step 5: Update RecordingBroadcaster

Edit `packages/server-python/src/rfnry_chat_server/broadcast/recording.py` (the test-only broadcaster). Add `broadcast_thread_created` and `broadcast_thread_deleted` recording methods; remove `broadcast_thread_created_to_sids` and `broadcast_thread_deleted_to_sids`.

### Step 6: Update `ChatServer.publish_thread_created` and `publish_thread_deleted`

Edit `packages/server-python/src/rfnry_chat_server/server/chat_server.py:280-298`:

```python
async def publish_thread_created(self, thread: Thread) -> None:
    """Fan thread:created to every connected socket whose identity tenant
    matches the new thread, via the deterministic tenant room joined at
    connect time."""
    if self.broadcaster is None:
        return
    await self.broadcaster.broadcast_thread_created(
        thread,
        namespace_keys=self.namespace_keys,
    )

async def publish_thread_deleted(self, thread_id: str, tenant: TenantScope) -> None:
    """Fan thread:deleted to the tenant room. Tenant is passed explicitly
    because the row is gone by the time we broadcast."""
    if self.broadcaster is None:
        return
    await self.broadcaster.broadcast_thread_deleted(
        thread_id,
        tenant,
        namespace_keys=self.namespace_keys,
    )
```

### Step 7: Delete the dead code

In `chat_server.py`:
- Delete `_collect_tenant_targets` (line ~300).
- The `if targets:` guard in `publish_thread_created` and `publish_thread_deleted` is gone (the room emit is a no-op if no one is in the room).

In `socketio/server.py`:
- Delete `self._sid_identities: dict[str, Identity] = {}` from `__init__`.
- Delete `self._sid_identities[sid] = identity` from `on_connect`.
- Delete `self._sid_identities.pop(sid, None)` from the `except` block of `on_connect`.
- Delete `self._sid_identities.pop(sid, None)` from `on_disconnect`.
- Delete the `connected_identities` method on `ThreadNamespace` (line ~223).
- Delete the `connected_identities` method on `ChatSocketIO` (line ~547).

In `broadcast/socketio.py`:
- Delete `broadcast_thread_created_to_sids` (line ~95).
- Delete `broadcast_thread_deleted_to_sids` (line ~109).

### Step 8: Run the tenant-isolation test

Run: `cd packages/server-python && uv run pytest tests/socketio/...::test_thread_created_emits_only_to_matching_tenant_room -xvs`

Expected: PASS. The contract held.

### Step 9: Run full server suite

Run: `cd packages/server-python && uv run poe dev`

Expected: all green. Some existing tests may have asserted the per-SID broadcast shape (e.g. `RecordingBroadcaster.thread_created_to_sids_calls`) — update those assertions to read from the new recorder fields, **not** the other way around.

### Step 10: Commit

```bash
git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/
git -C /home/frndvrgs/software/rfnry/chat commit -m "$(cat <<'EOF'
perf(server): tenant-scoped thread broadcasts emit to a single room

Replaces per-SID broadcast loops (broadcast_thread_created_to_sids,
broadcast_thread_deleted_to_sids) with single-room emits to
tenant:<path>, where each authenticated socket auto-joined its tenant
room on connect. Removes _sid_identities, connected_identities,
_collect_tenant_targets — none had a use outside the broadcast path.

At 1000 connected sockets in one tenant, a thread:created broadcast
goes from 1000 sequential sio.emit awaits to 1 single sio.emit(room=...).
EOF
)"
```

---

## T5 — Update READMEs  (docs)

**Why:** R12 changes the manual streaming pattern documented in `packages/client-python/README.md`. The example uses `client.begin_run(...)` and reads `run.id`. Without an update, every consumer copy-pasting the example will break on 0.2.0.

**Files:**
- Modify: `packages/client-python/README.md` (Streaming section, Manual example)
- Modify: `packages/server-python/README.md` if it documents the public Run API (likely not — server's run API is HTTP/socket-level, not Python-callable)

### Step 1: Read both READMEs

Find every instance of `begin_run`, `end_run`, and `run.id` / `run.status` in the README files. Run:

```bash
grep -n "begin_run\|end_run\|run\.id\|run\.status" packages/*/README.md
```

### Step 2: Rewrite the manual streaming example in the Python client README

Locate the section. The current example is:

```python
# Manual: coroutine handler opens its own run.
@client.on_message()
async def reply(ctx, send):
    run = await client.begin_run(ctx.event.thread_id, triggered_by_event_id=ctx.event.id)
    try:
        async with send.message_stream(run_id=run.id) as stream:
            async for token in my_llm.stream(ctx.event):
                await stream.write(token)
    finally:
        await client.end_run(run.id)
```

Replace with:

```python
# Manual: coroutine handler opens its own run. begin_run returns the
# run_id directly; call client.get_run(run_id) if you need the full Run.
@client.on_message()
async def reply(ctx, send):
    run_id = await client.begin_run(ctx.event.thread_id, triggered_by_event_id=ctx.event.id)
    try:
        async with send.message_stream(run_id=run_id) as stream:
            async for token in my_llm.stream(ctx.event):
                await stream.write(token)
    finally:
        await client.end_run(run_id)
```

### Step 3: Add a brief note on `get_run` near the example

Add a sentence after the example:

> `begin_run` returns the `run_id` as a string (saving an HTTP round-trip). If you need the hydrated `Run` object — e.g. for status reporting — call `await client.get_run(run_id)` explicitly.

### Step 4: Audit the server README for any begin_run/end_run mentions

Run: `grep -n "begin_run\|end_run" packages/server-python/README.md`

If hits exist (the server README documents `run:begin` and `run:end` as socket events, not Python methods, so likely no change needed), update accordingly.

### Step 5: Commit

```bash
git -C /home/frndvrgs/software/rfnry/chat add packages/client-python/README.md packages/server-python/README.md
git -C /home/frndvrgs/software/rfnry/chat commit -m "docs: update README examples for begin_run/end_run id-only return"
```

---

## T6 — Bump both Python packages to 0.2.0  (release)

**Why:** R12 is a breaking change to the Python client's public API. Pre-1.0 minor bump signals breaking change per semver convention. Both packages bump together because they're released in lockstep and depend on the same protocol contract.

**Files:**
- Modify: `packages/server-python/pyproject.toml:3` (`version = "0.1.1"` → `"0.2.0"`)
- Modify: `packages/client-python/pyproject.toml:3` (same)

### Step 1: Bump server version

Edit `packages/server-python/pyproject.toml`:
```toml
version = "0.2.0"
```

### Step 2: Bump client version

Edit `packages/client-python/pyproject.toml`:
```toml
version = "0.2.0"
```

### Step 3: Verify nothing else references the old version

Run:
```bash
grep -rn "0\.1\.1" packages/server-python/src packages/client-python/src
```

The `__version__` attributes are derived from `importlib.metadata.version(...)` so no source changes needed. If anything else hardcodes the version, update it.

### Step 4: Commit

```bash
git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/pyproject.toml packages/client-python/pyproject.toml
git -C /home/frndvrgs/software/rfnry/chat commit -m "chore: bump rfnry-chat-{server,client} to 0.2.0 (R12 breaking change)"
```

### Step 5: (Optional) Add a CHANGELOG entry

If the project has a CHANGELOG, add the 0.2.0 entry. If not, the PR description should serve as the changelog. Don't create a CHANGELOG just for this — defer to PR description.

---

## T7 — Final verification

### Step 1: Full test suites

```bash
cd packages/server-python && uv run poe dev
cd ../client-python && uv run poe dev
cd ../client-react && npm run check && npm run typecheck && npm run test
```

The React client doesn't change in this plan but should still pass (no behavioral coupling expected).

Expected: all green.

### Step 2: Build artifacts

```bash
cd packages/server-python && uv run poe build
cd ../client-python && uv run poe build
```

Expected: wheels in each `dist/` named `rfnry_chat_*-0.2.0-py3-none-any.whl`.

### Step 3: Manual smoke test

If there's a working example or dev fixture:
1. Start a server with `namespace_keys=["org"]`.
2. Connect two clients with different tenants.
3. Create a thread in tenant A.
4. Assert the tenant B client did NOT receive `thread:created`.
5. From an agent client, run a manual streaming handler (per the updated README pattern); confirm tokens flow.

If no such fixture exists, write a one-off script that connects two clients (different tenants), publishes a thread in tenant A, and asserts only tenant A's client receives the broadcast. Throwaway script — don't commit it.

### Step 4: Git log review

Run: `git log --oneline main..HEAD`

Expected: 6 commits (T1–T6 — T7 is verification, no commit). Each scoped, each with a clear `fix/feat/perf/chore/docs` prefix. The T2 commit must include the `BREAKING CHANGE:` footer for semver-aware tooling.

### Step 5: Open the PR

```bash
gh pr create --title "perf(tier 2): tenant rooms + run API ergonomics (0.2.0)" --body "$(cat <<'EOF'
## Summary

Tier 2 perf fixes from `.tresor/profile-2026-04-22/final-performance-report.md`:

- **R11 (tenant rooms)**: replaces O(n) per-SID broadcast loops with O(1) room emits. Each authenticated socket auto-joins a `tenant:<path>` room on connect; `thread:created` and `thread:deleted` now emit to that room directly.
- **R12 (run API)**: `ChatClient.begin_run` returns `str` (the run_id) instead of a hydrated `Run`. `ChatClient.end_run` returns `None`. New `ChatClient.get_run(run_id) -> Run` for callers that need hydration. Cuts the manual-streaming round-trip cost from 4 hops to 1 per lifecycle event.
- **Server-side**: `create_run` uses `RETURNING` so the returned object reflects persisted state.

Both Python packages bump to **0.2.0** per pre-1.0 semver convention for breaking changes.

## BREAKING CHANGES

- `ChatClient.begin_run(...)` now returns `str` (was `Run`). Callers needing the full Run should call `await client.get_run(run_id)`.
- `ChatClient.end_run(...)` now returns `None` (was `Run`). Same migration path.
- `Broadcaster.broadcast_thread_created_to_sids` and `broadcast_thread_deleted_to_sids` removed; replaced by `broadcast_thread_created` / `broadcast_thread_deleted` that take a tenant and emit to a room. Custom Broadcaster implementers must update.
- `ChatSocketIO.connected_identities()` removed (no longer needed). External callers should not have been using this; flagged for completeness.

## Test plan

- [ ] Tenant isolation: thread:created for tenant A doesn't reach tenant B sockets (covered by T4 step 1 test)
- [ ] begin_run returns str (covered by T2 step 2 tests)
- [ ] end_run returns None
- [ ] get_run hydrates a Run object
- [ ] create_run RETURNING contract holds (covered by T1 test)
- [ ] Manual smoke test of streaming through the updated README pattern

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## What's deferred to a follow-up plan

R13–R18 are smaller Tier 2 items that don't share design overhead with R11/R12. They could each ship as a one-off PR or be batched into a "Tier 2b — small wins" plan:

- **R13**: Add partial index `runs_active_started ON runs (started_at) WHERE status IN ('pending', 'running')` for the watchdog sweep.
- **R14**: Parallelize watchdog stale-run transitions with `asyncio.gather`.
- **R15**: Parse `toEvent(raw)` once at the React provider level, broadcast typed `Event` to all handler hooks (avoids N parses per stream:delta with N mounted hooks).
- **R16**: Replace serial `for/await` in Python client's `FrameDispatcher` and `InboxDispatcher` with `asyncio.gather`.
- **R17**: `useThreadIsWorking` derives directly from store without materializing `Run[]`.
- **R18**: `useThreadActions`: separate `isPending` from the stable callback memo.

Tier 3 (R19–R26) stays opportunistic — apply when adjacent code is touched.
