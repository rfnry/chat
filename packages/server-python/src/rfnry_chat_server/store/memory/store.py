from __future__ import annotations

from datetime import UTC, datetime

from rfnry_chat_protocol import (
    Event,
    Identity,
    Run,
    RunError,
    RunStatus,
    TenantScope,
    Thread,
    ThreadMember,
    ThreadPatch,
    matches,
)

from rfnry_chat_server.store.types import EventCursor, Page, ThreadCursor


class InMemoryChatStore:
    """ChatStore backed by dicts. Zero dependencies, not thread-safe, not
    durable — intended for examples, tests, and local development."""

    def __init__(self) -> None:
        self._threads: dict[str, Thread] = {}
        self._events: dict[str, Event] = {}
        self._events_by_thread: dict[str, list[str]] = {}
        self._runs: dict[str, Run] = {}
        self._members: dict[str, dict[str, ThreadMember]] = {}

    # threads

    async def create_thread(self, thread: Thread) -> Thread:
        self._threads[thread.id] = thread
        self._events_by_thread.setdefault(thread.id, [])
        self._members.setdefault(thread.id, {})
        return thread

    async def get_thread(self, thread_id: str) -> Thread | None:
        return self._threads.get(thread_id)

    async def list_threads(
        self,
        tenant_filter: TenantScope,
        cursor: ThreadCursor | None = None,
        limit: int = 50,
    ) -> Page[Thread]:
        threads = [t for t in self._threads.values() if matches(t.tenant, tenant_filter)]
        threads.sort(key=lambda t: (t.created_at, t.id), reverse=True)
        if cursor is not None:
            threads = [t for t in threads if (t.created_at, t.id) < (cursor.created_at, cursor.id)]
        items = threads[:limit]
        next_cursor: ThreadCursor | None = None
        if len(threads) > limit and items:
            last = items[-1]
            next_cursor = ThreadCursor(created_at=last.created_at, id=last.id)
        return Page[Thread](items=items, next_cursor=next_cursor)

    async def update_thread(self, thread_id: str, patch: ThreadPatch) -> Thread:
        current = self._threads.get(thread_id)
        if current is None:
            raise LookupError(f"thread not found: {thread_id}")
        updates: dict[str, object] = {"updated_at": datetime.now(UTC)}
        if patch.tenant is not None:
            updates["tenant"] = patch.tenant
        if patch.metadata is not None:
            updates["metadata"] = patch.metadata
        updated = current.model_copy(update=updates)
        self._threads[thread_id] = updated
        return updated

    async def delete_thread(self, thread_id: str) -> None:
        self._threads.pop(thread_id, None)
        for eid in self._events_by_thread.pop(thread_id, []):
            self._events.pop(eid, None)
        self._members.pop(thread_id, None)
        for run_id in [r.id for r in self._runs.values() if r.thread_id == thread_id]:
            self._runs.pop(run_id, None)

    # events

    async def append_event(self, event: Event) -> Event:
        self._events[event.id] = event
        self._events_by_thread.setdefault(event.thread_id, []).append(event.id)
        return event

    async def get_event(self, event_id: str) -> Event | None:
        return self._events.get(event_id)

    async def list_events(
        self,
        thread_id: str,
        since: EventCursor | None = None,
        until: EventCursor | None = None,
        limit: int = 100,
        types: list[str] | None = None,
    ) -> Page[Event]:
        ids = self._events_by_thread.get(thread_id, [])
        events = [self._events[i] for i in ids]
        events.sort(key=lambda e: (e.created_at, e.id))
        if since is not None:
            events = [e for e in events if (e.created_at, e.id) > (since.created_at, since.id)]
        if until is not None:
            events = [e for e in events if (e.created_at, e.id) < (until.created_at, until.id)]
        if types is not None:
            events = [e for e in events if e.type in types]
        items = events[:limit]
        next_cursor: EventCursor | None = None
        if len(events) > limit and items:
            last = items[-1]
            next_cursor = EventCursor(created_at=last.created_at, id=last.id)
        return Page[Event](items=items, next_cursor=next_cursor)

    # runs

    async def create_run(self, run: Run) -> Run:
        self._runs[run.id] = run
        return run

    async def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        error: RunError | None = None,
    ) -> Run:
        current = self._runs.get(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")
        updates: dict[str, object | None] = {"status": status, "error": error}
        if status in ("completed", "failed", "cancelled") and current.completed_at is None:
            updates["completed_at"] = datetime.now(UTC)
        updated = current.model_copy(update=updates)
        self._runs[run_id] = updated
        return updated

    async def find_run_by_idempotency_key(self, thread_id: str, key: str) -> Run | None:
        for run in self._runs.values():
            if run.thread_id == thread_id and run.idempotency_key == key:
                return run
        return None

    async def find_active_run(self, thread_id: str, actor_id: str) -> Run | None:
        for run in self._runs.values():
            if (
                run.thread_id == thread_id
                and run.actor.id == actor_id
                and run.status in ("pending", "running")
            ):
                return run
        return None

    async def find_runs_started_before(
        self,
        *,
        statuses: tuple[RunStatus, ...],
        threshold: datetime,
        limit: int = 100,
    ) -> list[Run]:
        stale = [
            run for run in self._runs.values()
            if run.status in statuses and run.started_at < threshold
        ]
        stale.sort(key=lambda r: r.started_at)
        return stale[:limit]

    # members

    async def add_member(
        self,
        thread_id: str,
        identity: Identity,
        added_by: Identity,
        role: str = "member",
    ) -> ThreadMember:
        members = self._members.setdefault(thread_id, {})
        existing = members.get(identity.id)
        if existing is not None:
            return existing
        member = ThreadMember(
            thread_id=thread_id,
            identity_id=identity.id,
            identity=identity,
            role=role,
            added_at=datetime.now(UTC),
            added_by=added_by,
        )
        members[identity.id] = member
        return member

    async def remove_member(self, thread_id: str, identity_id: str) -> None:
        members = self._members.get(thread_id)
        if members is not None:
            members.pop(identity_id, None)

    async def list_members(self, thread_id: str) -> list[ThreadMember]:
        members = self._members.get(thread_id, {})
        return sorted(members.values(), key=lambda m: m.added_at)

    async def is_member(self, thread_id: str, identity_id: str) -> bool:
        members = self._members.get(thread_id)
        return members is not None and identity_id in members
