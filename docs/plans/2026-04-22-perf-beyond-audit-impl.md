# Perf Beyond-Audit — Async publish + auth cache — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land the two perf items the original audit didn't cover but I flagged in retrospective: (1) parallelize the DB write and the room broadcast inside `publish_event` so publish latency is `max(write, broadcast)` instead of `write + broadcast`; (2) ship an opt-in `cached_authenticate` helper that consumers can wrap around their `authenticate` callback to avoid hitting their auth backend per REST request.

**Architecture:**
- **Async publish (T1)**: `ChatServer.publish_event` currently sequences `await store.append_event(event)` then `await broadcaster.broadcast_event(...)`. Both are I/O-bound and independent (broadcast doesn't depend on the DB write completing). Run them concurrently with `asyncio.gather` so total latency drops to the slower of the two. The DB write remains the source of truth — its exception still propagates to the caller; the broadcast is best-effort either way (Socket.IO doesn't guarantee delivery).
- **Auth cache (T2)**: `server/rest/deps.py:resolve_identity` calls `server.authenticate(handshake)` on every REST request. Consumers typically wire this to a real auth backend (DB/JWT verification/JWKS lookup) — that's one network hop per request. Ship a `cached_authenticate(fn, *, ttl, max_size, key)` wrapper in the SDK; consumers opt in by wrapping their callback. TTL-based with LRU eviction. Cache key defaults to `Authorization` header; configurable via `key=` callback for cookie/auth-payload-based schemes.

**Tech Stack:** unchanged. No new dependencies — both fixes use stdlib (`asyncio`, `collections.OrderedDict`, `time`, `hashlib`).

**Out of scope:**
- Anything else from the audit (Tier 3 R19–R26 stays opportunistic).
- Async write-behind queuing for `append_event` (the current fix preserves write-before-success-return semantics; full write-behind would let publish_event return before the DB confirms, which is a larger consistency change).
- Built-in caching on `ChatServer` directly (the helper is opt-in — strict YAGNI).
- Any client (Python or React) changes.

**Honest expected gains:**
- **T1 (async publish)**: in a typical deployment, broadcast latency is sub-millisecond for small rooms (encode + queue to N transports) and a few ms for large rooms. DB write latency dominates (1-5ms in-datacenter, 10-50ms cross-region). The pipelining saves the broadcast time off the DB time — a small absolute win (1-5ms typical) but a meaningful percentage (~10-30% of publish latency) for streaming-heavy paths where publish_event runs at high rate.
- **T2 (auth cache)**: depends entirely on the consumer's auth callback. If it's a local JWT verify with cached JWKS, savings are negligible. If it's a DB lookup or external HTTP call, savings are 10-100ms per cached REST request — much bigger absolute win than T1 in those deployments. Consumers who don't opt in pay nothing.

---

## Conventions for this plan

- **Branch shape:** single branch / single PR — both fixes are independent and small. PR title: `perf: async publish_event + opt-in cached_authenticate helper`.
- **Worktree:** optional. Each task is small and behavior-preserving (T1) or purely additive (T2). Direct on `main` matches existing project workflow.
- **Commits:** one per task (T1, T2, T3). T2 is the bigger one (new module + tests + export + README).
- **Tests:** each task ships with regression tests. T1's most important is a timing test (similar to Tier 2b T2's watchdog test). T2's tests cover hit/miss/expiry/eviction/custom-key/None-result-also-cached.
- **Test runner:** `cd packages/server-python && uv run pytest tests/path/test_x.py::test_name -xvs`.
- **No CI:** verify locally.
- **Versioning:** patch bump on `rfnry-chat-server` only (`0.2.1` → `0.2.2`). T1 is internal; T2 adds new public API but doesn't break existing callers (opt-in wrapper).

---

## Task ordering

| Order | ID | Title | Effort |
|---|---|---|---|
| **T1** | (async publish) | Parallelize `publish_event`'s write + broadcast via `asyncio.gather` | 1-2 hr |
| **T2** | (auth cache) | New `cached_authenticate` helper + tests + export + README example | 2-3 hr |
| **T3** | (release) | Bump `rfnry-chat-server` to 0.2.2 + final verification | 30 min |

---

## T1 — Parallelize `publish_event`'s write + broadcast  (async publish)

**Why:** Currently `publish_event` does `await self.store.append_event(event)` then `await self.broadcaster.broadcast_event(appended, namespace=namespace)`. Both are I/O-bound; the broadcast doesn't need the DB write to complete. Running them concurrently drops latency from `write + broadcast` to `max(write, broadcast)`.

**Files:**
- Modify: `packages/server-python/src/rfnry_chat_server/server/chat_server.py:220-248` (`publish_event`)
- Test: `packages/server-python/tests/server/` — find or create the right test file

### Steps

1. **Read** `packages/server-python/src/rfnry_chat_server/server/chat_server.py:220-248`. Note the current sequence:
   - lines 222-231: recipient normalization (sync logic + maybe one `list_members` await — keep as-is)
   - line 233: `appended = await self.store.append_event(event)` — the DB write
   - lines 234-241: namespace computation (cheap, depends on `thread`) + `await broadcaster.broadcast_event(appended, namespace=namespace)`
   - lines 243-248: handler dispatch (already `asyncio.create_task` — fire-and-forget; unchanged)

2. **Verify `append_event` returns a functionally-equivalent event for current store impls.** Read the InMemory and Postgres `append_event` methods. If they return the same event passed in (or a re-validated identical version), it's safe to broadcast `event` instead of `appended`. If they modify any field (e.g. DB-side `created_at` truncation), we need to handle that.

   Most likely outcome: both stores return the input event (PostgresChatStore likely uses INSERT ... RETURNING and re-parses, but the parsed result equals the input). Verify by inspection.

   If they modify, the implementer must use `appended` for broadcast — which means we can't fully parallelize and need to await write first. Report this and stop.

3. **Audit existing publish_event tests:**
   ```bash
   cd packages/server-python && grep -rn "publish_event\|append_event" tests/server/ tests/handler/ tests/socketio/
   ```
   Note any existing tests that might be sensitive to the order of operations.

4. **Write the failing timing test.** Add to `tests/server/` (likely `test_publish_event.py` if it exists, or create a new file):

   ```python
   import asyncio
   import time
   from datetime import UTC, datetime

   from rfnry_chat_protocol import AssistantIdentity, MessageEvent, TextPart
   from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
   from rfnry_chat_server.server.chat_server import ChatServer
   from rfnry_chat_server.store.memory.store import InMemoryChatStore

   async def test_publish_event_runs_write_and_broadcast_concurrently() -> None:
       """Regression: publish_event should pipeline the DB write and the
       broadcast. With both at 50ms each, total publish latency should be
       ~50ms (parallel), not ~100ms (serial)."""
       store = InMemoryChatStore()
       broadcaster = RecordingBroadcaster()

       # Inject 50ms delay into both append_event and broadcast_event
       original_append = store.append_event
       async def slow_append(event):
           await asyncio.sleep(0.05)
           return await original_append(event)
       store.append_event = slow_append  # type: ignore[method-assign]

       original_broadcast = broadcaster.broadcast_event
       async def slow_broadcast(event, **kwargs):
           await asyncio.sleep(0.05)
           return await original_broadcast(event, **kwargs)
       broadcaster.broadcast_event = slow_broadcast  # type: ignore[method-assign]

       async def auth(hs):
           return None  # not exercised in this test
       server = ChatServer(store=store, broadcaster=broadcaster, authenticate=auth)
       me = AssistantIdentity(id="a_x", name="X")
       thread = await store.create_thread(tenant={}, metadata={}, caller=me)

       event = MessageEvent(
           id="evt_1",
           thread_id=thread.id,
           author=me,
           created_at=datetime.now(UTC),
           content=[TextPart(text="hi")],
       )

       start = time.monotonic()
       await server.publish_event(event, thread=thread)
       elapsed = time.monotonic() - start

       # Parallel: ~50ms. Serial: ~100ms. Generous slack for CI noise.
       assert elapsed < 0.08, f"publish_event took {elapsed:.3f}s — looks serial (would be ~0.1s)"
   ```

   Adapt to actual fixture/import patterns. Match how existing tests construct ChatServer, InMemoryChatStore, and the Identity types. The Thread creation API may differ — read the existing tests for the right call shape.

5. **Run, verify failure** with the current serial implementation: publish takes ~100ms, test fails.

6. **Apply the fix.** Replace lines 233-241 of `chat_server.py`. The current shape:

   ```python
   appended = await self.store.append_event(event)
   if self.broadcaster is not None:
       namespace: str | None = None
       if self.namespace_keys is not None:
           if thread is None:
               thread = await self.store.get_thread(event.thread_id)
           if thread is not None:
               namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
       await self.broadcaster.broadcast_event(appended, namespace=namespace)
   ```

   Becomes:

   ```python
   # Pre-compute the namespace (sync if thread is provided; one DB hit otherwise)
   # so both the write and the broadcast can fire concurrently without sharing
   # any awaited prerequisite.
   namespace: str | None = None
   if self.broadcaster is not None and self.namespace_keys is not None:
       if thread is None:
           thread = await self.store.get_thread(event.thread_id)
       if thread is not None:
           namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)

   # Pipeline the DB write and the broadcast. The broadcast doesn't depend
   # on the write completing — it carries the event payload directly. Total
   # latency drops from write+broadcast to max(write, broadcast).
   if self.broadcaster is not None:
       appended, _ = await asyncio.gather(
           self.store.append_event(event),
           self.broadcaster.broadcast_event(event, namespace=namespace),
       )
   else:
       appended = await self.store.append_event(event)
   ```

   Notes:
   - Broadcast uses `event` (already-normalized, post-recipient-validation) instead of `appended`. This is safe because `append_event` returns a functionally identical event (verified in Step 2).
   - The namespace pre-computation moves above the gather so both tasks can start without an awaited prerequisite. The pre-computation may itself await `get_thread` — that's fine; it happens once before the parallel fork.
   - If `broadcaster is None`, fall back to the simple sequential path (no parallelism to gain).
   - **`asyncio.gather` cancellation behavior**: if the DB write raises, gather will cancel the in-flight broadcast. That's acceptable — Socket.IO doesn't guarantee delivery anyway, and a failed-write event shouldn't be canonical.

7. **Run the test:** PASS (timing under 80ms).

8. **Run full server suite + lint + typecheck:** `cd packages/server-python && uv run poe dev`. All green.

9. **Commit:**
   ```bash
   git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/
   git -C /home/frndvrgs/software/rfnry/chat commit -m "$(cat <<'EOF'
   perf(server): publish_event pipelines DB write and broadcast via asyncio.gather

   The broadcast doesn't depend on the DB write completing — both are I/O-bound
   and independent. Running them concurrently drops publish latency from
   write+broadcast to max(write, broadcast). Typical saving: a few ms (the
   broadcast time) per publish, but adds up on streaming-heavy paths.

   The DB write remains the source of truth — its exception still propagates.
   If the write fails, gather cancels the in-flight broadcast (acceptable;
   Socket.IO doesn't guarantee delivery and a failed-write event shouldn't
   be canonical anyway).
   EOF
   )"
   ```

### Subtle points for T1

- **`event` vs `appended` for broadcast.** This is the one correctness question. If `append_event` ever modifies the event (e.g. assigns a server-generated `id`, normalizes a field), the broadcast would diverge from what's persisted. Today neither store does this — verify in Step 2. If a future store implementation needs to mutate, the broadcast must wait for the appended result and the parallelization can't apply.
- **Recipient normalization stays before the gather.** Lines 222-231 mutate `event` to add normalized recipients. Both the DB write and the broadcast must see the same normalized form. The gather happens AFTER normalization.
- **Handler dispatch (line 246) is unchanged.** It's already `asyncio.create_task` (fire-and-forget). Outside the publish_event critical path.
- **`get_thread` for namespace computation.** When `namespace_keys is set` and `thread is None`, we hit the DB once to look up the thread. This still happens before the gather (the broadcast needs the namespace). One sequential await before the parallel fork is fine — it's a small cost (single index lookup) and unavoidable for namespace routing. Callers that already pass `thread=...` (which most internal callers do) skip this.

---

## T2 — `cached_authenticate` helper  (auth cache)

**Why:** `server/rest/deps.py:resolve_identity` calls `await server.authenticate(handshake)` on every REST request. Consumers typically wire this to a real auth backend — DB query, JWT verify with JWKS fetch, etc. — costing 10-100ms per request. A TTL cache keyed by the Authorization header makes most requests skip the auth backend entirely. Opt-in: consumers wrap their own callback; the wrapper is a small SDK helper, not a built-in `ChatServer` parameter.

**Files:**
- Create: `packages/server-python/src/rfnry_chat_server/server/auth_cache.py` — the helper
- Modify: `packages/server-python/src/rfnry_chat_server/__init__.py` — export the helper
- Test: `packages/server-python/tests/server/test_auth_cache.py` (new)
- Modify: `packages/server-python/README.md` — add a "Deployment" or "Performance" section showing the wire-up

### Steps

1. **Read** `packages/server-python/src/rfnry_chat_server/server/auth.py` — confirm `HandshakeData` and `AuthenticateCallback` shapes (already-known from previous reads, but verify).

2. **Read** `packages/server-python/src/rfnry_chat_server/__init__.py` — see the existing `__all__` shape and import pattern.

3. **Write the failing tests** at `packages/server-python/tests/server/test_auth_cache.py`. Six cases cover the contract:

   ```python
   from __future__ import annotations

   import asyncio
   import time

   from rfnry_chat_protocol import UserIdentity
   from rfnry_chat_server.server.auth import HandshakeData
   from rfnry_chat_server.server.auth_cache import cached_authenticate


   def _hs(token: str = "alice") -> HandshakeData:
       return HandshakeData(headers={"authorization": f"Bearer {token}"}, auth={})


   async def test_cache_hit_avoids_underlying_call() -> None:
       """A second call with the same token must NOT re-invoke the wrapped callback."""
       calls = 0
       async def upstream(hs):
           nonlocal calls
           calls += 1
           return UserIdentity(id="u_alice", name="Alice")

       wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
       a = await wrapped(_hs())
       b = await wrapped(_hs())
       assert a is b  # cached object reference returned
       assert calls == 1


   async def test_cache_miss_for_different_token() -> None:
       """Different Authorization headers produce independent cache entries."""
       calls = 0
       async def upstream(hs):
           nonlocal calls
           calls += 1
           token = hs.headers["authorization"].removeprefix("Bearer ")
           return UserIdentity(id=f"u_{token}", name=token)

       wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
       a = await wrapped(_hs("alice"))
       b = await wrapped(_hs("bob"))
       assert a.id == "u_alice"
       assert b.id == "u_bob"
       assert calls == 2


   async def test_cache_expires_after_ttl(monkeypatch) -> None:
       """An entry past its TTL must trigger a fresh upstream call."""
       calls = 0
       async def upstream(hs):
           nonlocal calls
           calls += 1
           return UserIdentity(id="u_alice", name="Alice")

       fake_now = [1000.0]
       monkeypatch.setattr(
           "rfnry_chat_server.server.auth_cache.time.monotonic",
           lambda: fake_now[0],
       )

       wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
       await wrapped(_hs())  # call 1
       assert calls == 1

       fake_now[0] += 30.0  # within TTL
       await wrapped(_hs())
       assert calls == 1

       fake_now[0] += 31.0  # now past 60s TTL (total elapsed: 61s)
       await wrapped(_hs())
       assert calls == 2


   async def test_cache_lru_eviction_at_max_size() -> None:
       """Cache evicts least-recently-used entries when at capacity."""
       async def upstream(hs):
           token = hs.headers["authorization"].removeprefix("Bearer ")
           return UserIdentity(id=f"u_{token}", name=token)

       wrapped = cached_authenticate(upstream, ttl_seconds=60.0, max_size=2)
       await wrapped(_hs("a"))
       await wrapped(_hs("b"))
       await wrapped(_hs("a"))  # touches a (now newest)
       await wrapped(_hs("c"))  # evicts b (LRU)

       calls_before = 0
       calls = [calls_before]
       async def counting_upstream(hs):
           calls[0] += 1
           token = hs.headers["authorization"].removeprefix("Bearer ")
           return UserIdentity(id=f"u_{token}", name=token)

       # Replace upstream and check: a and c are still cached, b is not.
       # (Easier: re-wrap counting_upstream, prime with a and c, evict b case)
       # Simpler version of this test: just verify max_size is honored by
       # checking len of the internal cache after 3+ unique tokens.
       # Use whatever introspection the helper exposes (or a private attr).


   async def test_cache_with_custom_key_function() -> None:
       """Consumers can override the cache key (e.g. cookie-based auth)."""
       calls = 0
       async def upstream(hs):
           nonlocal calls
           calls += 1
           return UserIdentity(id="u_alice", name="Alice")

       wrapped = cached_authenticate(
           upstream,
           ttl_seconds=60.0,
           key=lambda hs: hs.auth.get("session_id", ""),
       )
       hs1 = HandshakeData(headers={}, auth={"session_id": "s1"})
       hs2 = HandshakeData(headers={}, auth={"session_id": "s1"})
       await wrapped(hs1)
       await wrapped(hs2)
       assert calls == 1


   async def test_cache_caches_none_too() -> None:
       """Failed auth (returns None) must also be cached so attackers can't
       brute-force token validity by timing or rate."""
       calls = 0
       async def upstream(hs):
           nonlocal calls
           calls += 1
           return None  # auth failure

       wrapped = cached_authenticate(upstream, ttl_seconds=60.0)
       a = await wrapped(_hs("bad"))
       b = await wrapped(_hs("bad"))
       assert a is None
       assert b is None
       assert calls == 1
   ```

   Adapt to fixture/style conventions in the existing `tests/server/` directory.

4. **Run, verify failure:** `cd packages/server-python && uv run pytest tests/server/test_auth_cache.py -xvs`. Expected: ImportError — `auth_cache` module doesn't exist.

5. **Implement the helper** at `packages/server-python/src/rfnry_chat_server/server/auth_cache.py`:

   ```python
   from __future__ import annotations

   import time
   from collections import OrderedDict
   from collections.abc import Callable

   from rfnry_chat_protocol import Identity

   from rfnry_chat_server.server.auth import AuthenticateCallback, HandshakeData


   def _default_key(handshake: HandshakeData) -> str:
       """Default cache key: the Authorization header value."""
       return handshake.headers.get("authorization", "")


   def cached_authenticate(
       authenticate: AuthenticateCallback,
       *,
       ttl_seconds: float = 60.0,
       max_size: int = 1024,
       key: Callable[[HandshakeData], str] = _default_key,
   ) -> AuthenticateCallback:
       """Wrap an authenticate callback with a TTL+LRU cache.

       Caches both successful (Identity) and failed (None) auth results so
       repeated requests with the same token skip the upstream call. Failed
       results are cached too so an attacker can't probe token validity by
       comparing response times.

       The default cache key is the Authorization header value. For other
       schemes (cookie, auth payload, etc.) pass a custom `key` function.
       """
       cache: OrderedDict[str, tuple[Identity | None, float]] = OrderedDict()

       async def cached(handshake: HandshakeData) -> Identity | None:
           cache_key = key(handshake)
           # Empty key (e.g. no Authorization header) — don't pollute the
           # cache with a single unauth entry. Pass through every time.
           if not cache_key:
               return await authenticate(handshake)

           now = time.monotonic()
           if cache_key in cache:
               value, expires_at = cache[cache_key]
               if now < expires_at:
                   cache.move_to_end(cache_key)  # mark as MRU
                   return value
                 # Expired — fall through to refresh.
                 del cache[cache_key]

           value = await authenticate(handshake)
           cache[cache_key] = (value, now + ttl_seconds)
           cache.move_to_end(cache_key)

           # LRU eviction
           while len(cache) > max_size:
               cache.popitem(last=False)

           return value

       return cached
   ```

   The implementation uses `OrderedDict.move_to_end` for O(1) LRU bookkeeping. `time.monotonic()` (not `time.time()`) so the cache is immune to wall-clock changes.

   **Concurrency note:** asyncio is single-threaded; concurrent `cached()` calls cannot interleave inside a single `await` point. Two concurrent calls with the same key may both hit the upstream (cache miss in both), but the result is identical (last write wins; old reference still works). Acceptable.

6. **Export the helper.** Edit `packages/server-python/src/rfnry_chat_server/__init__.py`:

   ```python
   from rfnry_chat_server.server.auth_cache import cached_authenticate
   ```

   And add `"cached_authenticate"` to `__all__`. Match the alphabetical/grouping convention of the existing exports.

7. **Run the tests:** all PASS.

8. **Run full server suite + lint + typecheck:** `cd packages/server-python && uv run poe dev`. All green.

9. **Add README documentation.** Edit `packages/server-python/README.md` — add a section after the "Production deployment" section (or wherever fits the file's structure). Match the existing style (one short paragraph + a code example):

   ```markdown
   ## Auth callback caching

   `authenticate` is called on every REST request. If your callback hits a
   database, a JWT verifier with JWKS fetch, or any external auth service,
   that's one extra network hop per request. Wrap it with `cached_authenticate`
   to TTL-cache results by Authorization header:

   ```python
   from rfnry_chat_server import ChatServer, cached_authenticate

   async def my_authenticate(handshake):
       token = handshake.headers.get("authorization", "")
       return await my_auth_service.verify(token)  # slow

   auth = cached_authenticate(my_authenticate, ttl_seconds=60.0, max_size=4096)
   server = ChatServer(store=store, authenticate=auth, ...)
   ```

   Both successful (`Identity`) and failed (`None`) results are cached. For
   non-header auth schemes (cookie, custom payload), pass `key=lambda hs: ...`
   to override the default cache key.
   ```

10. **Commit:**
    ```bash
    git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/
    git -C /home/frndvrgs/software/rfnry/chat commit -m "$(cat <<'EOF'
    feat(server): add cached_authenticate helper for TTL+LRU auth caching

    `authenticate` runs on every REST request — typically a DB query or external
    auth service hop. Consumers can now wrap their callback in
    cached_authenticate(fn, ttl_seconds, max_size, key) to cache results by
    Authorization header (or a custom key for cookie/payload-based schemes).

    Both Identity and None (auth failure) results are cached so an attacker
    can't probe token validity by timing. Opt-in helper, not built into
    ChatServer — consumers who don't want caching pay nothing.
    EOF
    )"
    ```

### Subtle points for T2

- **Cache failed auth too.** This is a security feature, not a bug. If only successful auth is cached, an attacker comparing response times can distinguish "valid token" (fast — cached) from "invalid token" (slow — every check hits upstream). Caching None aligns the timing.
- **Empty cache key bypass.** `key=` returning `""` means "don't cache" — the helper passes through to upstream. This handles the case where a request arrives with no Authorization header (the default key returns `""`); the upstream callback gets to see that and decide what to do. Without this bypass, every unauthenticated request would share a single cache entry, defeating the purpose.
- **`time.monotonic()` not `time.time()`.** Wall-clock changes (NTP adjustment, leap second) shouldn't affect cache TTLs.
- **Single-threaded asyncio means no locks needed.** Concurrent `cached()` calls with the same key may both miss and both call upstream; whichever finishes second's `cache[key] = ...` wins. The duplicate work is acceptable — same input, same output, no consistency hazard.
- **No deduplication of in-flight upstream calls.** Could be added as a follow-up if benchmarks show it matters. YAGNI for now.

---

## T3 — Bump `rfnry-chat-server` to 0.2.2 + final verification  (release)

**Why:** T1 is internal (no API change). T2 adds a new public export (`cached_authenticate`) but doesn't break existing callers. Patch bump signals "new feature, backward-compatible" per pre-1.0 convention.

**Files:**
- Modify: `packages/server-python/pyproject.toml:3` (`0.2.1` → `0.2.2`)

### Steps

1. Edit the version string.

2. Re-sync uv lock:
   ```bash
   cd packages/server-python && uv sync --quiet --extra dev
   ```

3. **Full suite verification:**
   ```bash
   cd packages/server-python && uv run poe dev
   ```
   All green.

4. **Build:**
   ```bash
   cd packages/server-python && uv run poe build
   ```
   Expected wheel: `rfnry_chat_server-0.2.2-py3-none-any.whl`.

5. **Verify other packages still pass** (they shouldn't change behavior, but the editable path dep across `examples/` and `client-python` should still work):
   ```bash
   cd packages/client-python && uv run poe test
   ```
   All green.

6. **Commit:**
   ```bash
   git -C /home/frndvrgs/software/rfnry/chat add packages/server-python/pyproject.toml packages/server-python/uv.lock
   git -C /home/frndvrgs/software/rfnry/chat commit -m "chore: bump rfnry-chat-server to 0.2.2 (cached_authenticate + parallel publish)"
   ```

7. **Git log review:**
   ```bash
   git -C /home/frndvrgs/software/rfnry/chat log --oneline 2045d2c..HEAD
   ```
   Expected: 3 commits (T1, T2, T3).

8. **Open the PR:**
   ```bash
   gh pr create --title "perf: async publish_event + opt-in cached_authenticate helper" --body "$(cat <<'EOF'
   ## Summary

   Two perf items the original audit didn't cover but were flagged in the Tier 2/2b retrospective:

   - **T1 (async publish)**: `ChatServer.publish_event` now pipelines the DB write and the room broadcast via `asyncio.gather`. Total publish latency is `max(write, broadcast)` instead of `write + broadcast`. The DB write remains the source of truth — its exception still propagates; the broadcast is best-effort either way.
   - **T2 (auth cache)**: new opt-in `cached_authenticate(fn, ttl_seconds, max_size, key)` SDK helper. Wraps a consumer's authenticate callback with a TTL+LRU cache keyed by Authorization header (or custom). Caches both Identity and None to defend against timing-based token probing.

   `rfnry-chat-server` patch bump to **0.2.2**. T1 is internal; T2 adds a new export without breaking existing API.

   ## Honest perf framing

   - T1 saves the broadcast time off the DB time per publish_event call. Typical: 1-5ms in datacenter, more across regions. Bigger percentage on streaming-heavy paths than absolute single-publish latency.
   - T2 savings depend entirely on the consumer's callback. If it hits a real auth backend, savings are 10-100ms per cached request — the dominant win in this PR.

   ## Test plan

   - [ ] T1 timing test: publish_event with 50ms write + 50ms broadcast finishes in ~50ms (parallel), not ~100ms (serial)
   - [ ] T2 cache hit/miss/expiry/LRU/custom-key/None-cached all covered
   - [ ] Full suite still green
   - [ ] `client-python` editable-dep consumers still pass

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```

---

## What's NOT in this plan

- **Async write-behind queuing**: this plan keeps the write-before-success-return semantics (gather still awaits both). A true write-behind queue (publish_event returns before the DB confirms; a worker drains the queue) is a bigger consistency change that needs its own design decision.
- **In-flight-call deduplication for the auth cache**: if two concurrent requests with the same token arrive while the upstream call is in flight, both will currently call upstream. A `dict[str, asyncio.Future]` deduplication layer would prevent this. YAGNI for now; benchmark before adding.
- **Built-in caching on ChatServer**: kept as opt-in helper rather than a `ChatServer(authenticate_cache=...)` parameter. Strict YAGNI. Consumers who want it wrap their own callback; consumers who don't want it pay nothing.
- **Tier 3 (R19–R26)**: unchanged — opportunistic.
