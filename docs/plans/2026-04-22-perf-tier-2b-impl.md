# Perf Tier 2b — Small wins (R13–R18) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land the six smaller Tier 2 perf fixes (R13–R18) from `.tresor/profile-2026-04-22/final-performance-report.md` that didn't make the cut for the R11+R12 plan. Together they tighten the watchdog, eliminate redundant `toEvent` parsing across mounted React handler hooks, derive `useThreadIsWorking` directly from store dict size, decouple `isPending` from the stable callback memo, and parallelize Python client frame dispatch.

**Architecture:**
- **R13 + R14 (server)**: a partial index `runs_active_started ON runs (started_at) WHERE status IN ('pending', 'running')` so the watchdog sweep query is index-bounded; watchdog transitions go through `asyncio.gather` instead of a serial `for`.
- **R15 (React)**: provider parses each incoming `event` frame **once** via `toEvent(raw)` and exposes the typed `Event` through a per-thread subscriber registry on the context. `useHandler` and family read from that registry instead of re-parsing every socket frame independently. At N mounted hooks, parses go from N×events/sec to 1×events/sec.
- **R16 (Python client)**: `FrameDispatcher` and `InboxDispatcher` use `asyncio.gather` for handler fan-out (mirrors what `Dispatcher` already does for event handlers).
- **R17 (React)**: `useThreadIsWorking` reads `state.activeRuns[threadId]` directly (count via `Object.keys(...).length > 0` selector) instead of calling `useThreadActiveRuns` and materializing a `Run[]` array.
- **R18 (React)**: `useThreadActions` separates `isPending` from the memoized callback object — components that don't read `isPending` no longer re-render on transition state changes.

**Tech Stack:** unchanged. No new dependencies.

**Out of scope:**
- R12 (Python client run API) — already shipped in Tier 2 as 0.2.0.
- R11 (tenant rooms) — already shipped in Tier 2.
- Tier 3 (R19–R26) — opportunistic, no plan.
- Anything not numbered R13–R18.

**Source reports** (read first):
- `.tresor/profile-2026-04-22/final-performance-report.md` — R13–R18 each have a row in the Tier 2 table.
- `.tresor/profile-2026-04-22/phase-1-server.md` — R13/R14 detail at "HIGH: Watchdog transitions stale runs serially…".
- `.tresor/profile-2026-04-22/phase-1-client.md` — R16 detail at "HIGH: `FrameDispatcher` and `InboxDispatcher` run handlers serially".
- `.tresor/profile-2026-04-22/phase-1-react.md` — R15/R17/R18 each have a section.

---

## Conventions for this plan

- **Branch shape:** all six tasks are independent with no shared abstractions. They could ship as 6 separate PRs, but per the user's earlier preference (Tier 1, Tier 2 each landed as one branch), bundle them as a single branch with one task per commit. Single PR titled "perf(tier 2b): small wins".
- **Worktree:** optional. Each task is small (under 200 lines net) and behavior-preserving; doing it directly on `main` (project's existing convention) is fine.
- **Commits:** one focused commit per task (T1–T6). Final commit (T7) bumps versions and is the only release-coupled change.
- **Tests:** each task ships with a regression test. The test for R15 is the most important — it must prove that one event parses once across N mounted hooks.
- **Test runners:**
  - `cd packages/server-python && uv run pytest tests/path/test_x.py::test_name -xvs`
  - `cd packages/client-python && uv run pytest tests/path/test_x.py::test_name -xvs`
  - `cd packages/client-react && npx vitest run tests/path/file.test.ts -t "name"`
- **No CI:** verify locally per package.
- **Versioning:** all three packages bump as patch:
  - `rfnry-chat-server`: `0.2.0 → 0.2.1`
  - `rfnry-chat-client`: `0.2.0 → 0.2.1`
  - `@rfnry/chat-client-react`: `0.1.0 → 0.1.1`

---

## Task ordering

Server first (smallest blast radius), then Python client, then React (biggest). R15 last because it's the most invasive.

| Order | ID | Title | Package |
|---|---|---|---|
| **T1** | R13 | Add `runs_active_started` partial index for the watchdog sweep | server-python |
| **T2** | R14 | Parallelize watchdog stale-run transitions with `asyncio.gather` | server-python |
| **T3** | R16 | `FrameDispatcher` + `InboxDispatcher` fan handlers with `asyncio.gather` | client-python |
| **T4** | R17 | `useThreadIsWorking` derives boolean from store dict; no Run[] materialization | client-react |
| **T5** | R18 | `useThreadActions`: separate `isPending` from callback memo | client-react |
| **T6** | R15 | React provider parses `event` once; expose typed-event registry on context | client-react |
| **T7** | (release) | Version bumps + final verification | all |

---

## T1 — Add `runs_active_started` partial index for the watchdog sweep  (R13)

**Why:** `_sweep_stale_runs` calls `store.find_runs_started_before(statuses=("pending", "running"), threshold=...)`. Without an index that matches this WHERE clause, the query falls back to a sequential scan over the `runs` table. The existing `runs_thread (thread_id, started_at DESC)` index doesn't help because the watchdog query has no `thread_id` filter. A partial index on `(started_at)` filtered to active statuses gives the planner exactly what it needs.

**Files:**
- Modify: `packages/server-python/src/rfnry_chat_server/store/postgres/schema.sql` (add the index)
- Test: `packages/server-python/tests/store/test_postgres_runs.py` (add a contract test that the index exists)

### Steps

1. **Read** `packages/server-python/src/rfnry_chat_server/store/postgres/schema.sql` (full file) to see the existing index conventions. Note the pattern uses `CREATE INDEX IF NOT EXISTS`.

2. **Read** `packages/server-python/src/rfnry_chat_server/store/postgres/store.py` `find_runs_started_before` method — understand the exact query shape so the index covers it.

3. **Read** `packages/server-python/tests/store/test_postgres_runs.py` and adjacent files to learn how schema-level tests are structured (e.g. `test_setup.py`).

4. **Write the failing test** in `tests/store/test_postgres_runs.py`:

   ```python
   async def test_runs_active_started_index_exists(clean_db: asyncpg.Pool) -> None:
       """Regression for R13: the watchdog sweep query (status IN
       ('pending','running') AND started_at < threshold) must be backed by a
       partial index. Without it, the sweep is a sequential scan over the
       full runs table and gets unusably slow under load."""
       store = PostgresChatStore(pool=clean_db)
       await store.ensure_schema()
       async with clean_db.acquire() as conn:
           rows = await conn.fetch(
               """
               SELECT indexname FROM pg_indexes
               WHERE tablename = 'runs' AND indexname = 'runs_active_started'
               """
           )
       assert len(rows) == 1, "runs_active_started partial index must exist"
   ```

   Adapt to actual fixture names (the prior Tier 2 test used `clean_db`/`PostgresChatStore` directly; match it).

5. **Run, verify failure:** `cd packages/server-python && uv run pytest tests/store/test_postgres_runs.py::test_runs_active_started_index_exists -xvs`. Expected: FAIL — index doesn't exist.

6. **Add the index** to `schema.sql`. Place it next to the existing `runs_thread` index (around line 34):

   ```sql
   CREATE INDEX IF NOT EXISTS runs_active_started
     ON runs (started_at)
     WHERE status IN ('pending', 'running');
   ```

7. **Run the test:** PASS.

8. **Run full server suite:** `cd packages/server-python && uv run poe dev`. All green.

9. **Sanity-check** the planner uses the new index. From a Python REPL or a one-off script (not a committed file):
   ```python
   await conn.execute("EXPLAIN SELECT * FROM runs WHERE status IN ('pending','running') AND started_at < now()")
   ```
   Should mention `runs_active_started`. Skip if `EXPLAIN` adds friction — the test that the index exists is sufficient for plan compliance; plan-shape verification is a future concern.

10. **Commit:**
    ```bash
    git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/src/rfnry_chat_server/store/postgres/schema.sql packages/server-python/tests/store/test_postgres_runs.py
    git -C /home/frndvrgs/software/rfnry/chat commit -m "perf(server): partial index runs_active_started for watchdog sweep query"
    ```

---

## T2 — Parallelize watchdog stale-run transitions with `asyncio.gather`  (R14)

**Why:** `_sweep_stale_runs` iterates the stale-run list with `for run in stale: await self.end_run(...)`. Each `end_run` is multiple DB round-trips. With 100 stale runs that's 400+ sequential DB queries per sweep. `asyncio.gather` runs them concurrently; the per-run work is unchanged but wall-clock time becomes ~max(per-run-time) instead of sum.

**Files:**
- Modify: `packages/server-python/src/rfnry_chat_server/server/chat_server.py:163-179` (`_sweep_stale_runs`)
- Test: `packages/server-python/tests/server/` — find or create the right server-test file

### Steps

1. **Read** `packages/server-python/src/rfnry_chat_server/server/chat_server.py:163-179` for `_sweep_stale_runs`. Note the surrounding `_watchdog_loop` context and the `RunError` import.

2. **Audit existing watchdog tests:**
   ```bash
   cd packages/server-python && grep -rn "watchdog\|_sweep_stale_runs\|run_timeout_seconds" tests/
   ```
   There's `tests/store/test_postgres_watchdog.py` from Tier 1 — read it to learn the test pattern.

3. **Write the failing test** that proves serial vs parallel behavior. The test injects multiple stale runs and asserts that the sweep completes in roughly the time of one transition (proving concurrency), not the sum:

   ```python
   async def test_watchdog_sweep_processes_stale_runs_concurrently() -> None:
       """Regression for R14: watchdog must process stale runs concurrently,
       not serially. With 10 stale runs and a 50ms-per-end_run delay, the
       sweep should finish in ~50ms, not ~500ms."""
       # Build a ChatServer with an InMemoryChatStore wrapped to inject a
       # 50ms delay in update_run_status, simulating slow DB transitions.
       # Seed 10 stale runs.
       # Time _sweep_stale_runs(). Assert duration < 200ms (well under the
       # 500ms serial floor; well above the 50ms ideal — leaves slack for CI noise).
       ...
   ```

   Match existing test patterns. If the codebase already has a "delayed store" wrapper, reuse it. Otherwise build a thin one inline (the Tier 1 RecordingStore pattern).

4. **Run, verify failure:** the test should time out or exceed 200ms on serial code.

5. **Apply the fix.** Replace the loop in `_sweep_stale_runs`:

   ```python
   async def _sweep_stale_runs(self) -> None:
       threshold = datetime.now(UTC) - timedelta(seconds=self.run_timeout_seconds)
       stale = await self.store.find_runs_started_before(
           statuses=("pending", "running"),
           threshold=threshold,
       )
       if not stale:
           return

       async def _timeout_one(run_id: str) -> None:
           try:
               await self.end_run(
                   run_id=run_id,
                   error=RunError(
                       code="timeout",
                       message=f"run exceeded {self.run_timeout_seconds}s without end signal",
                   ),
               )
           except Exception:
               _log.exception("watchdog failed to timeout run %s", run_id)

       await asyncio.gather(*(_timeout_one(run.id) for run in stale))
   ```

   The `try/except` moves inside `_timeout_one` so one failed run doesn't fail the whole `gather`. Each task's exception is logged and swallowed individually — same semantics as the prior loop.

6. **Run the test:** PASS.

7. **Full suite:** `uv run poe dev`. All green. Existing watchdog tests should pass unchanged — the contract (eventual completion of every stale run, individual failure isolation) is preserved.

8. **Commit:**
    ```bash
    git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/
    git -C /home/frndvrgs/software/rfnry/chat commit -m "perf(server): parallelize watchdog stale-run transitions with asyncio.gather"
    ```

---

## T3 — `FrameDispatcher` + `InboxDispatcher` fan handlers with `asyncio.gather`  (R16)

**Why:** Both dispatchers iterate their handler lists serially: each handler's `await` blocks the next handler from starting. The sibling `Dispatcher` (event handlers) already uses `asyncio.gather` for exactly this reason. Aligning the three dispatchers means an I/O-bound `@on_thread_updated` handler doesn't delay the `@on_thread_updated` listener registered next to it.

For `InboxDispatcher`, the auto-join (`client.join_thread(...)`) STAYS serial-with-handlers — handlers may assume they're joined. Only the user-handler fan-out parallelizes.

**Files:**
- Modify: `packages/client-python/src/rfnry_chat_client/frames.py` (three `feed_*` methods)
- Modify: `packages/client-python/src/rfnry_chat_client/inbox.py` (the user-handler loop in `feed`)
- Test: `packages/client-python/tests/test_frames.py`, `tests/test_inbox.py`

### Steps

1. **Read** `packages/client-python/src/rfnry_chat_client/frames.py` and `inbox.py` end-to-end. Note the `_maybe_await` helper in `frames.py` — it'll need to coexist with `gather` (only awaitables go into the gather; sync handlers run immediately).

2. **Read** `packages/client-python/src/rfnry_chat_client/dispatch.py` to see how `Dispatcher` uses `gather` — match the pattern.

3. **Write failing tests.** The most direct shape:

   In `tests/test_frames.py`:
   ```python
   async def test_feed_thread_updated_fans_handlers_concurrently() -> None:
       """R16: when multiple thread:updated handlers are registered, the
       FrameDispatcher must invoke them concurrently — one slow handler must
       not block the next handler from starting."""
       fd = FrameDispatcher()
       order: list[str] = []
       started = asyncio.Event()

       @fd.register_thread_updated
       async def slow(thread: Thread) -> None:
           started.set()
           await asyncio.sleep(0.05)
           order.append("slow_done")

       @fd.register_thread_updated
       async def fast(thread: Thread) -> None:
           await started.wait()  # only proceeds once slow has started
           order.append("fast_done")

       await fd.feed_thread_updated(_thread_payload())
       # fast must complete before slow because slow sleeps 50ms after starting.
       assert order == ["fast_done", "slow_done"]
   ```

   Add equivalents for `feed_members_updated` and `feed_run_updated`.

   In `tests/test_inbox.py`, an analogous test for `InboxDispatcher.feed`:

   ```python
   async def test_inbox_feed_fans_user_handlers_concurrently() -> None:
       """R16: invite handlers must run concurrently after the auto-join
       completes. Auto-join stays serialized because handlers may assume
       they're already joined to the room."""
       # Mock client with a fast join_thread.
       # Register two handlers; assert their ordering proves concurrency.
       ...
   ```

4. **Run, verify failure:** ordering on serial code is reversed (`["slow_done", "fast_done"]`).

5. **Apply the fix in `frames.py`.** Each `feed_*` becomes:

   ```python
   async def feed_thread_updated(self, raw: dict[str, Any]) -> None:
       thread = Thread.model_validate(raw)
       results = [handler(thread) for handler in self._thread_updated]
       awaitables = [r for r in results if inspect.isawaitable(r)]
       if awaitables:
           await asyncio.gather(*awaitables)
   ```

   Same pattern for `feed_members_updated` and `feed_run_updated`. Sync handlers (`Awaitable[None] | None`) execute immediately during the list comprehension; only the awaitables join the gather. The `_maybe_await` helper becomes unused — delete it if so.

6. **Apply the fix in `inbox.py`.** The auto-join (`await self._client.join_thread(...)`) stays as-is. Replace the user-handler loop:

   ```python
   results = [handler(frame) for handler in self._handlers]
   awaitables = [r for r in results if inspect.isawaitable(r)]
   if awaitables:
       await asyncio.gather(*awaitables)
   ```

7. **Run the tests:** PASS (ordering now `["fast_done", "slow_done"]`).

8. **Full client suite + lint + typecheck:** `cd packages/client-python && uv run poe dev`. All green.

9. **Commit:**
    ```bash
    git -C /home/frndvrgs/software/rfnry/chat add packages/client-python/
    git -C /home/frndvrgs/software/rfnry/chat commit -m "perf(client-python): FrameDispatcher and InboxDispatcher fan handlers concurrently"
    ```

---

## T4 — `useThreadIsWorking` derives boolean from store dict  (R17)

**Why:** Currently `useThreadIsWorking` calls `useThreadActiveRuns(threadId)` which materializes `Object.values(state.activeRuns[threadId] ?? {})` — an O(n) array build, wrapped in `useShallow` for stability. For a boolean read, this is wasted work. Reading the dict's key count directly via the store is O(1) and doesn't need `useShallow`.

**Files:**
- Modify: `packages/client-react/src/hooks/useThreadIsWorking.ts` (entire file — currently 6 lines)
- Test: `packages/client-react/tests/hooks/` — add a regression test

### Steps

1. **Read** the current file:
   ```ts
   import { useThreadActiveRuns } from './useThreadActiveRuns'
   export function useThreadIsWorking(threadId: string | null): boolean {
     const runs = useThreadActiveRuns(threadId)
     return runs.length > 0
   }
   ```

2. **Read** `packages/client-react/src/hooks/useThreadActiveRuns.ts` (for the import pattern of `useStore` from zustand) and `packages/client-react/tests/hooks/useThreadActiveRuns.test.tsx` (for the test harness pattern — `harness(store)` wrapper, `makeRun` helper).

3. **Write the failing test** at `packages/client-react/tests/hooks/useThreadIsWorking.test.tsx`:

   ```tsx
   import { act, render } from '@testing-library/react'
   import { describe, expect, it } from 'vitest'
   import { useThreadIsWorking } from '../../src/hooks/useThreadIsWorking'
   // ... wrapper + makeRun helpers from useThreadActiveRuns.test.tsx (extract to shared if convenient)

   describe('useThreadIsWorking', () => {
     it('returns false for empty thread', () => { /* ... */ })
     it('returns true when one run exists', () => { /* ... */ })

     it('does not re-render when the run set changes but stays non-empty', () => {
       const store = createChatStore()
       store.getState().actions.upsertRun(makeRun('r1', 't_A'))
       let renderCount = 0
       function Probe() {
         renderCount++
         const working = useThreadIsWorking('t_A')
         return <div>{String(working)}</div>
       }
       render(<Wrapper><Probe /></Wrapper>)
       const baseline = renderCount

       // Adding a second run keeps the boolean `true` — no re-render.
       act(() => { store.getState().actions.upsertRun(makeRun('r2', 't_A')) })

       // R17: the hook returns the SAME boolean reference (true), so React bails.
       expect(renderCount).toBe(baseline)
     })
   })
   ```

   The third test is the key one — it proves the hook doesn't re-render on changes that don't flip the boolean. Under the prior implementation (delegating to `useThreadActiveRuns` + `useShallow` over `Object.values`), adding a second run would change the array contents and might trigger a re-render even with `useShallow` (depends on shallow-equality check across element identity).

4. **Run, verify pass on current code** for tests 1 and 2 (they're behavior pins). Test 3 — depending on `useShallow`'s implementation — may pass or fail on prior code. If it passes, that's still OK: the new implementation will preserve the property at lower cost.

5. **Implement the fix:**

   ```ts
   import { useStore } from 'zustand'
   import { useChatStore } from './useChatClient'

   export function useThreadIsWorking(threadId: string | null): boolean {
     const store = useChatStore()
     return useStore(store, (state) => {
       if (!threadId) return false
       const runs = state.activeRuns[threadId]
       return runs !== undefined && Object.keys(runs).length > 0
     })
   }
   ```

   The selector returns a boolean. Zustand's default `Object.is` comparator is sufficient — no `useShallow` needed (booleans are reference-stable).

6. **Run the tests:** all PASS.

7. **Full React suite + check + typecheck:** `cd packages/client-react && npm run check && npm run typecheck && npm run test`. All green.

8. **Commit:**
    ```bash
    git -C /home/frndvrgs/software/rfnry/chat add packages/client-react/
    git -C /home/frndvrgs/software/rfnry/chat commit -m "perf(client-react): useThreadIsWorking derives boolean from store dict size"
    ```

---

## T5 — `useThreadActions`: separate `isPending` from callback memo  (R18)

**Why:** `useThreadActions` returns one big `useMemo`-wrapped object that includes `isPending`. The memo's dep array is `[client, threadId, isPending, withTransition]` — every transition state change recreates the entire actions object. Components that don't read `isPending` (most of them — `isPending` is for spinners, not for action triggers) re-render anyway because the `actions` object identity changed.

The fix: keep `isPending` and the actions in separate stable references. Two shapes work:
- **(a)** Return a tuple: `const { actions, isPending } = useThreadActions(threadId)`. Breaks the existing API.
- **(b)** Keep the merged shape but build it without `isPending` in the memo's deps; assign `isPending` after the memo. Preserves API.

Use **(b)** — non-breaking.

**Files:**
- Modify: `packages/client-react/src/hooks/useThreadActions.ts:41-99`
- Test: `packages/client-react/tests/hooks/useThreadActions.pending.test.tsx` (already exists per the file list)

### Steps

1. **Read** `packages/client-react/src/hooks/useThreadActions.ts` end-to-end.

2. **Read** `packages/client-react/tests/hooks/useThreadActions.pending.test.tsx` to see what it currently asserts. Match its style for the new test.

3. **Write the failing test.** Add to `useThreadActions.pending.test.tsx`:

   ```tsx
   it('does not change action callback identity when isPending toggles', async () => {
     const { result, rerender } = renderHook(
       () => useThreadActions('t_A'),
       { wrapper: Wrapper }
     )
     const sendBefore = result.current.send
     // Trigger a transition that flips isPending true then back to false.
     await act(async () => { await result.current.send({ content: [{ type: 'text', text: 'x' }] }) })
     rerender()
     const sendAfter = result.current.send
     // R18: the send callback should be the same reference across the
     // isPending true→false cycle. Components memoizing on `send` should
     // not re-mount their render path.
     expect(sendAfter).toBe(sendBefore)
   })
   ```

   Adapt to actual fixtures (`Wrapper`, mocked client, etc. — the existing test file already sets these up).

4. **Run, verify failure** — under current code, `sendBefore !== sendAfter` because the whole actions object is recreated when `isPending` changes.

5. **Implement the fix:**

   ```ts
   export function useThreadActions(threadId: string | null): UseThreadActions {
     const client = useChatClient()
     const [isPending, startTransition] = useTransition()

     const withTransition = useCallback(
       <T>(fn: () => Promise<T>): Promise<T> =>
         new Promise<T>((resolve, reject) => {
           startTransition(async () => {
             try { resolve(await fn()) } catch (err) { reject(err as Error) }
           })
         }),
       []
     )

     // Build the action callbacks once per (client, threadId, withTransition).
     // isPending is excluded from the deps so toggling it doesn't recreate
     // the callbacks — components reading only `send` etc. don't re-render.
     const callbacks = useMemo(
       () => ({
         send: (draft: EventDraft) => {
           if (!threadId) throw new Error('threadId is required')
           return withTransition(() => client.sendMessage(threadId, draft))
         },
         emit: (event: Record<string, unknown> & { type: string }) => {
           if (!threadId) throw new Error('threadId is required')
           return withTransition(() => client.emitEvent({ ...event, threadId }))
         },
         beginRun: (opts: { triggeredByEventId?: string; idempotencyKey?: string } = {}) => {
           if (!threadId) throw new Error('threadId is required')
           return withTransition(() => client.beginRun(threadId, opts))
         },
         endRun: (runId: string, opts: { error?: RunError } = {}) =>
           withTransition(() => client.endRun(runId, opts)),
         cancelRun: (runId: string) => withTransition(() => client.cancelRun(runId)),
         streamMessage: ({ runId, author, metadata, onFinalEvent }: {
           runId: string; author: Identity; metadata?: Record<string, unknown>;
           onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void;
         }) => {
           if (!threadId) throw new Error('threadId is required')
           return client.streamMessage({ threadId, runId, author, metadata, onFinalEvent })
         },
         streamReasoning: ({ runId, author, metadata, onFinalEvent }: {
           runId: string; author: Identity; metadata?: Record<string, unknown>;
           onFinalEvent?: (event: MessageEvent | ReasoningEvent) => Promise<void> | void;
         }) => {
           if (!threadId) throw new Error('threadId is required')
           return client.streamReasoning({ threadId, runId, author, metadata, onFinalEvent })
         },
         addMember: (identity: Identity, role: string = 'member') => {
           if (!threadId) throw new Error('threadId is required')
           return withTransition(() => client.addMember(threadId, identity, role))
         },
         removeMember: (identityId: string) => {
           if (!threadId) throw new Error('threadId is required')
           return withTransition(() => client.removeMember(threadId, identityId))
         },
         updateThread: (patch: ThreadPatch) => {
           if (!threadId) throw new Error('threadId is required')
           return withTransition(() => client.updateThread(threadId, patch))
         },
       }),
       [client, threadId, withTransition]  // NOTE: no isPending here
     )

     // Stitch isPending in. The returned object identity changes per render
     // (cheap), but `callbacks.send` etc. are stable across isPending toggles.
     // Consumers reading `actions.send` get a stable callback; consumers
     // reading `actions.isPending` get the live transition state.
     return { ...callbacks, isPending }
   }
   ```

   The trade: every render allocates a new outer object via spread. That's cheap. The win: `callbacks.send` (etc.) reference identity is stable across `isPending` toggles, so a `useEffect(() => {...}, [actions.send])` doesn't re-fire on transition state changes.

6. **Run the test:** PASS.

7. **Full suite:** all green.

8. **Commit:**
    ```bash
    git -C /home/frndvrgs/software/rfnry/chat add packages/client-react/
    git -C /home/frndvrgs/software/rfnry/chat commit -m "perf(client-react): useThreadActions stable callback identity across isPending toggles"
    ```

---

## T6 — React provider parses `event` once; expose typed-event registry on context  (R15)

**Why:** Currently every mounted `useHandler`/`useMessageHandler`/etc. calls `client.on('event', cb)` independently, and each callback does `toEvent(raw as never)` to parse. With N mounted hooks + the provider's own `addEvent` listener, every incoming `event` frame is parsed N+1 times. `toEvent` does discriminated-union pydantic-style validation — non-trivial cost at LLM token rates.

The fix: the provider parses each `event` frame **once** and dispatches the typed `Event` to a per-thread subscriber registry. `useHandler` subscribes to that registry instead of registering its own raw socket listener.

This is the largest change in Tier 2b but also the most measurable win — at 100 events/sec with 5 mounted hooks, parses go from 600/sec to 100/sec.

**Files:**
- Modify: `packages/client-react/src/provider/ChatContext.ts` (add registry to context value)
- Modify: `packages/client-react/src/provider/ChatProvider.tsx:80-90` (parse once + dispatch via registry)
- Modify: `packages/client-react/src/hooks/useHandler.ts` (subscribe via context registry instead of `client.on`)
- Test: `packages/client-react/tests/hooks/useHandler.test.tsx` — add a regression test counting parse calls

### Steps

1. **Read** all four files end-to-end:
   - `packages/client-react/src/provider/ChatContext.ts`
   - `packages/client-react/src/provider/ChatProvider.tsx`
   - `packages/client-react/src/hooks/useHandler.ts`
   - `packages/client-react/tests/hooks/useHandler.test.tsx`

2. **Design the registry shape.** Add to `ChatContext.ts`:

   ```ts
   import type { Event } from '@rfnry/chat-protocol'

   export type EventListener = (event: Event) => void

   export type EventRegistry = {
     subscribe(listener: EventListener): () => void  // returns unsubscribe
   }

   export type ChatContextValue = {
     client: ChatClient
     store: ChatStore
     events: EventRegistry  // NEW
   }
   ```

   The registry is a simple pub/sub. `useHandler` subscribes via `events.subscribe(listener)` and applies its own filters (event-type match, recipient match, self-author skip — same logic as today).

3. **Implement the registry in `ChatProvider.tsx`.** Inside `setup()`, after `client.connect()`:

   ```ts
   // Per-thread event subscribers. The provider parses each incoming
   // `event` frame ONCE and dispatches the typed Event to all listeners.
   // Mounted handler hooks subscribe here instead of calling client.on('event')
   // independently — at N mounted hooks, this drops parse calls from N+1
   // to 1 per incoming event.
   const eventListeners = new Set<EventListener>()
   const eventRegistry: EventRegistry = {
     subscribe(listener) {
       eventListeners.add(listener)
       return () => { eventListeners.delete(listener) }
     },
   }

   disposers.push(
     client.on('event', (data) => {
       const event = toEvent(data as never)
       store.getState().actions.addEvent(event)
       for (const listener of eventListeners) {
         try { listener(event) } catch (err) { console.error('handler error', err) }
       }
     })
   )
   ```

   Note: `addEvent` now takes the already-typed `Event` (it already does — `addEvent(toEvent(data))` was the prior pattern; the change is that we no longer call `toEvent` separately for handler dispatch).

   Pass `eventRegistry` into the context value:
   ```ts
   setValue({ client, store, events: eventRegistry })
   ```

4. **Rewrite `useHandler.ts`** to subscribe via the registry instead of `client.on`. The hook currently looks roughly like:

   ```ts
   export function useHandler(threadId: string | null, handler: EventHandler, opts?: ...) {
     const client = useChatClient()
     useEffect(() => {
       const dispose = client.on('event', (raw) => {
         const event = toEvent(raw as never)
         // filter by threadId, type, recipients, etc.
         handler(event)
       })
       return dispose
     }, [client, threadId, handler, ...opts])
   }
   ```

   New shape:

   ```ts
   import { useChatContext } from './useChatClient'  // or wherever the context hook lives

   export function useHandler(threadId: string | null, handler: EventHandler, opts?: ...) {
     const { events, client } = useChatContext()
     // Stable handlerRef so dep-array changes don't re-subscribe excessively.
     const handlerRef = useRef(handler)
     handlerRef.current = handler

     useEffect(() => {
       const listener: EventListener = (event) => {
         // Existing filter logic — match threadId, event type, apply
         // self-author skip / recipient filter unless allEvents=true.
         if (!shouldDispatch(event, threadId, client.identity, opts)) return
         handlerRef.current(event)
       }
       return events.subscribe(listener)
     }, [events, threadId, client.identity, opts?.allEvents, opts?.tool, opts?.eventType])
   }
   ```

   Carry over the existing filter logic exactly — don't lose any cases. The `useMessageHandler`, `useToolCallHandler`, etc. sugar wrappers don't change (they call `useHandler` with different `eventType`).

5. **Write the failing test.** Add to `tests/hooks/useHandler.test.tsx` (or a new file):

   ```tsx
   it('parses each incoming event once across N mounted handler hooks (R15)', async () => {
     const parseCount = { n: 0 }
     // Spy on toEvent. Easiest: vi.mock('@rfnry/chat-protocol') with a
     // wrapped toEvent that increments parseCount.
     // ... mount provider with 5 mounted useHandler hooks for the same thread
     // ... fire one socket frame
     // ... assert parseCount.n === 1 (was 6: 1 provider + 5 hooks)
   })
   ```

   The spy approach is the cleanest — wrap `toEvent` once, count calls, assert.

6. **Run, verify failure** on prior code (count would be N+1).

7. **Run target tests:** all PASS.

8. **Run full React suite:** `cd packages/client-react && npm run check && npm run typecheck && npm run test`. All green. Existing `useHandler` tests must continue to pass — the dispatch contract (which events fire, with what filters) is unchanged.

9. **Commit:**
    ```bash
    git -C /home/frndvrgs/software/rfnry/chat add packages/client-react/
    git -C /home/frndvrgs/software/rfnry/chat commit -m "perf(client-react): parse incoming events once at provider; hooks subscribe via context registry"
    ```

### Subtle points for T6

- **Filter logic must be preserved exactly.** The existing `useHandler` skips self-authored events by default and respects `recipients` lists. Carry over every filter case; an `allEvents: true` opt-out must still work.
- **Ordering**: prior code had each hook receive events in `client.on` registration order. New code uses a `Set` — iteration order is insertion order in JS engines. Same effective ordering, but worth noting.
- **Error isolation**: a thrown handler should not block other handlers. The provider wraps each `listener(event)` call in a try/catch (sketched above). Match how `Dispatcher` does this in the Python client (it uses `asyncio.gather(return_exceptions=True)` semantics).
- **Other event types**: this plan only covers the `event` channel (persisted Event types). The provider also handles `run:updated`, `thread:updated`, `members:updated`, `thread:invited`, `thread:created`, `thread:deleted`, `thread:cleared`. Each of those has its own parse cost but no analogous "N hooks subscribing independently" multiplier — they're handled once by the provider already. Don't expand scope to include them.

---

## T7 — Version bumps + final verification  (release)

**Why:** All six tasks are non-breaking (R13/R14 are server-internal; R15/R17/R18 are React-internal optimizations preserving hook contracts; R16 is Python-client-internal). Patch version bump for all three packages.

**Files:**
- Modify: `packages/server-python/pyproject.toml:3` (`0.2.0` → `0.2.1`)
- Modify: `packages/client-python/pyproject.toml:3` (`0.2.0` → `0.2.1`)
- Modify: `packages/client-react/package.json` (`"version": "0.1.0"` → `"0.1.1"`)

### Steps

1. Edit all three version strings.

2. Re-sync uv lock files:
   ```bash
   cd packages/server-python && uv sync --quiet --extra dev
   cd ../client-python && uv sync --quiet --extra dev
   ```
   This updates `uv.lock` to reflect the new versions.

3. **Full suite verification across all three packages:**
   ```bash
   cd packages/server-python && uv run poe dev
   cd ../client-python && uv run poe dev
   cd ../client-react && npm run check && npm run typecheck && npm run test
   ```
   All green.

4. **Build artifacts:**
   ```bash
   cd packages/server-python && uv run poe build
   cd ../client-python && uv run poe build
   cd ../client-react && npm run build
   ```
   Expected wheel names: `rfnry_chat_server-0.2.1-py3-none-any.whl`, `rfnry_chat_client-0.2.1-py3-none-any.whl`. React tsup output unchanged (CJS + ESM + DTS).

5. **Commit:**
   ```bash
   git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/pyproject.toml packages/server-python/uv.lock packages/client-python/pyproject.toml packages/client-python/uv.lock packages/client-react/package.json
   git -C /home/frndvrgs/software/rfnry/chat commit -m "chore: bump rfnry-chat-{server,client} to 0.2.1; @rfnry/chat-client-react to 0.1.1"
   ```

6. **Git log review:**
   ```bash
   git -C /home/frndvrgs/software/rfnry/chat log --oneline 5c4fad7..HEAD
   ```
   Expected: 7 commits (T1–T7), each scoped, each with an appropriate `perf/chore` prefix. No breaking-change footers (none of these are public API breaks).

7. **Open the PR:**
   ```bash
   gh pr create --title "perf(tier 2b): small wins (R13–R18)" --body "$(cat <<'EOF'
   ## Summary

   Tier 2b — six small perf fixes from `.tresor/profile-2026-04-22/final-performance-report.md`:

   - **R13**: partial index `runs_active_started` for the watchdog sweep query
   - **R14**: parallelize watchdog stale-run transitions with `asyncio.gather`
   - **R15**: React provider parses each `event` frame once; handler hooks subscribe via a typed-event registry on the context (drops parse calls from N+1 to 1 per event with N mounted hooks)
   - **R16**: Python client `FrameDispatcher` and `InboxDispatcher` fan handlers concurrently
   - **R17**: `useThreadIsWorking` derives a boolean directly from the store dict size; no `Run[]` materialization
   - **R18**: `useThreadActions` separates `isPending` from the callback memo so action callback identity is stable across transition toggles

   No breaking changes. Patch bumps:
   - `rfnry-chat-server`: 0.2.0 → 0.2.1
   - `rfnry-chat-client`: 0.2.0 → 0.2.1
   - `@rfnry/chat-client-react`: 0.1.0 → 0.1.1

   ## Test plan

   - [ ] Watchdog sweep with 100 stale runs completes in roughly 1× per-run latency, not 100×
   - [ ] R15 regression test: one event, 5 mounted hooks → 1 `toEvent` call
   - [ ] All hook tests still pass — the dispatch contract is unchanged
   - [ ] `useThreadActions.send` reference is stable across `isPending` toggles

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```

---

## What's NOT in this plan

- **Tier 3 (R19–R26)**: opportunistic — apply when adjacent code is touched.
- **Things the audit didn't cover** (worth considering separately):
  - Async DB writes — decouple `store.append_event` from `broadcaster.broadcast_event` so publish latency isn't gated by Postgres write time.
  - LRU cache on `authenticate` callback — every REST request currently calls it; a TTL cache by token hash would meaningfully reduce per-request auth cost. R24 in Tier 3 says "document this"; a small SDK-level cache wrapper would actually fix it.

These are not on the audit and not on this plan — flagged for future scoping decisions.
