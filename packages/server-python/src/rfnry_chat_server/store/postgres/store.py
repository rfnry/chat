from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg
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
    parse_event,
    parse_identity,
)

from rfnry_chat_server.store.types import EventCursor, Page, ThreadCursor


class PostgresChatStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_thread(self, thread: Thread) -> Thread:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO threads (id, tenant, metadata, created_at, updated_at)
                VALUES ($1, $2::jsonb, $3::jsonb, $4, $5)
                RETURNING id, tenant, metadata, created_at, updated_at
                """,
                thread.id,
                json.dumps(thread.tenant),
                json.dumps(thread.metadata),
                thread.created_at,
                thread.updated_at,
            )
        assert row is not None
        return _row_to_thread(row)

    async def get_thread(self, thread_id: str) -> Thread | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, tenant, metadata, created_at, updated_at FROM threads WHERE id = $1",
                thread_id,
            )
        return _row_to_thread(row) if row else None

    async def list_threads(
        self,
        tenant_filter: TenantScope,
        cursor: ThreadCursor | None = None,
        limit: int = 50,
    ) -> Page[Thread]:
        args: list[Any] = [json.dumps(tenant_filter)]
        where = ["$1::jsonb @> threads.tenant"]
        if cursor is not None:
            args.append(cursor.created_at)
            args.append(cursor.id)
            where.append(f"(threads.created_at, threads.id) < (${len(args) - 1}, ${len(args)})")
        args.append(limit + 1)
        sql = (
            "SELECT id, tenant, metadata, created_at, updated_at FROM threads WHERE "
            + " AND ".join(where)
            + f" ORDER BY created_at DESC, id DESC LIMIT ${len(args)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        items = [_row_to_thread(r) for r in rows[:limit]]
        next_cursor: ThreadCursor | None = None
        if len(rows) > limit and items:
            last = items[-1]
            next_cursor = ThreadCursor(created_at=last.created_at, id=last.id)
        return Page[Thread](items=items, next_cursor=next_cursor)

    async def update_thread(self, thread_id: str, patch: ThreadPatch) -> Thread:
        sets: list[str] = []
        args: list[Any] = [thread_id]
        if patch.tenant is not None:
            args.append(json.dumps(patch.tenant))
            sets.append(f"tenant = ${len(args)}::jsonb")
        if patch.metadata is not None:
            args.append(json.dumps(patch.metadata))
            sets.append(f"metadata = ${len(args)}::jsonb")
        args.append(datetime.now(UTC))
        sets.append(f"updated_at = ${len(args)}")
        sql = (
            f"UPDATE threads SET {', '.join(sets)} WHERE id = $1 RETURNING id, tenant, metadata, created_at, updated_at"
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *args)
        if row is None:
            raise LookupError(f"thread not found: {thread_id}")
        return _row_to_thread(row)

    async def delete_thread(self, thread_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM threads WHERE id = $1", thread_id)

    async def append_event(self, event: Event) -> Event:
        payload = event.model_dump(
            mode="json",
            exclude={
                "id",
                "thread_id",
                "run_id",
                "author",
                "created_at",
                "metadata",
                "client_id",
                "recipients",
                "type",
            },
            by_alias=True,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO events (
                    id, thread_id, run_id, type, author, payload,
                    metadata, client_id, recipients, created_at
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9::jsonb, $10)
                """,
                event.id,
                event.thread_id,
                event.run_id,
                event.type,
                json.dumps(event.author.model_dump(mode="json")),
                json.dumps(payload),
                json.dumps(event.metadata),
                event.client_id,
                json.dumps(event.recipients) if event.recipients is not None else None,
                event.created_at,
            )
        return event

    async def get_event(self, event_id: str) -> Event | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, thread_id, run_id, type, author, payload, metadata, client_id, recipients, created_at
                FROM events WHERE id = $1
                """,
                event_id,
            )
        return _row_to_event(row) if row else None

    async def list_events(
        self,
        thread_id: str,
        since: EventCursor | None = None,
        until: EventCursor | None = None,
        limit: int = 100,
        types: list[str] | None = None,
    ) -> Page[Event]:
        args: list[Any] = [thread_id]
        where = ["thread_id = $1"]
        if since is not None:
            args.append(since.created_at)
            args.append(since.id)
            where.append(f"(created_at, id) > (${len(args) - 1}, ${len(args)})")
        if until is not None:
            args.append(until.created_at)
            args.append(until.id)
            where.append(f"(created_at, id) < (${len(args) - 1}, ${len(args)})")
        if types is not None:
            args.append(types)
            where.append(f"type = ANY(${len(args)}::text[])")
        args.append(limit + 1)
        sql = (
            "SELECT id, thread_id, run_id, type, author, payload, metadata, client_id, recipients, created_at "
            "FROM events WHERE " + " AND ".join(where) + f" ORDER BY created_at, id LIMIT ${len(args)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        items = [_row_to_event(r) for r in rows[:limit]]
        next_cursor: EventCursor | None = None
        if len(rows) > limit and items:
            last = items[-1]
            next_cursor = EventCursor(created_at=last.created_at, id=last.id)
        return Page[Event](items=items, next_cursor=next_cursor)

    async def create_run(self, run: Run) -> Run:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO runs (id, thread_id, actor, triggered_by, status,
                                  error, idempotency_key, metadata, started_at, completed_at)
                VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6::jsonb, $7, $8::jsonb, $9, $10)
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
        return run

    async def get_run(self, run_id: str) -> Run | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, thread_id, actor, triggered_by, status, error,
                       idempotency_key, metadata, started_at, completed_at
                FROM runs WHERE id = $1
                """,
                run_id,
            )
        return _row_to_run(row) if row else None

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        error: RunError | None = None,
    ) -> Run:
        completed_at = datetime.now(UTC) if status in ("completed", "failed", "cancelled") else None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE runs SET status = $2, error = $3::jsonb,
                                completed_at = COALESCE($4, completed_at)
                WHERE id = $1
                RETURNING id, thread_id, actor, triggered_by, status, error,
                          idempotency_key, metadata, started_at, completed_at
                """,
                run_id,
                status,
                json.dumps(error.model_dump(mode="json")) if error else None,
                completed_at,
            )
        if row is None:
            raise LookupError(f"run not found: {run_id}")
        return _row_to_run(row)

    async def find_run_by_idempotency_key(self, thread_id: str, key: str) -> Run | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, thread_id, actor, triggered_by, status, error,
                       idempotency_key, metadata, started_at, completed_at
                FROM runs WHERE thread_id = $1 AND idempotency_key = $2
                """,
                thread_id,
                key,
            )
        return _row_to_run(row) if row else None

    async def find_active_run(self, thread_id: str, actor_id: str) -> Run | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, thread_id, actor, triggered_by, status, error,
                       idempotency_key, metadata, started_at, completed_at
                FROM runs
                WHERE thread_id = $1 AND actor->>'id' = $2
                  AND status IN ('pending', 'running')
                """,
                thread_id,
                actor_id,
            )
        return _row_to_run(row) if row else None

    async def find_runs_started_before(
        self,
        *,
        statuses: tuple[RunStatus, ...],
        threshold: datetime,
        limit: int = 100,
    ) -> list[Run]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, thread_id, actor, triggered_by, status, error,
                       idempotency_key, metadata, started_at, completed_at
                FROM runs
                WHERE status = ANY($1::text[]) AND started_at < $2
                ORDER BY started_at
                LIMIT $3
                """,
                list(statuses),
                threshold,
                limit,
            )
        return [_row_to_run(row) for row in rows]

    async def add_member(
        self,
        thread_id: str,
        identity: Identity,
        added_by: Identity,
        role: str = "member",
    ) -> ThreadMember:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO thread_members (thread_id, identity_id, identity, role, added_by)
                VALUES ($1, $2, $3::jsonb, $4, $5::jsonb)
                ON CONFLICT (thread_id, identity_id) DO NOTHING
                RETURNING thread_id, identity_id, identity, role, added_at, added_by
                """,
                thread_id,
                identity.id,
                json.dumps(identity.model_dump(mode="json")),
                role,
                json.dumps(added_by.model_dump(mode="json")),
            )
            if row is None:
                row = await conn.fetchrow(
                    """
                    SELECT thread_id, identity_id, identity, role, added_at, added_by
                    FROM thread_members WHERE thread_id = $1 AND identity_id = $2
                    """,
                    thread_id,
                    identity.id,
                )
        assert row is not None
        return _row_to_member(row)

    async def remove_member(self, thread_id: str, identity_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM thread_members WHERE thread_id = $1 AND identity_id = $2",
                thread_id,
                identity_id,
            )

    async def list_members(self, thread_id: str) -> list[ThreadMember]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT thread_id, identity_id, identity, role, added_at, added_by
                FROM thread_members WHERE thread_id = $1 ORDER BY added_at
                """,
                thread_id,
            )
        return [_row_to_member(r) for r in rows]

    async def is_member(self, thread_id: str, identity_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM thread_members WHERE thread_id = $1 AND identity_id = $2)",
                thread_id,
                identity_id,
            )
        return bool(result)


def _decode_jsonb(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_thread(row: asyncpg.Record) -> Thread:
    return Thread(
        id=row["id"],
        tenant=_decode_jsonb(row["tenant"]),
        metadata=_decode_jsonb(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_event(row: asyncpg.Record) -> Event:
    payload = _decode_jsonb(row["payload"])
    author = _decode_jsonb(row["author"])
    metadata = _decode_jsonb(row["metadata"])
    recipients = _decode_jsonb(row["recipients"]) if row["recipients"] is not None else None
    raw = {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "run_id": row["run_id"],
        "type": row["type"],
        "author": author,
        "metadata": metadata,
        "client_id": row["client_id"],
        "recipients": recipients,
        "created_at": row["created_at"],
        **payload,
    }
    return parse_event(raw)


def _row_to_run(row: asyncpg.Record) -> Run:
    actor = _decode_jsonb(row["actor"])
    triggered_by = _decode_jsonb(row["triggered_by"])
    error = _decode_jsonb(row["error"]) if row["error"] is not None else None
    metadata = _decode_jsonb(row["metadata"])
    return Run(
        id=row["id"],
        thread_id=row["thread_id"],
        actor=parse_identity(actor),
        triggered_by=parse_identity(triggered_by),
        status=row["status"],
        error=RunError.model_validate(error) if error else None,
        idempotency_key=row["idempotency_key"],
        metadata=metadata,
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def _row_to_member(row: asyncpg.Record) -> ThreadMember:
    identity = _decode_jsonb(row["identity"])
    added_by = _decode_jsonb(row["added_by"])
    return ThreadMember(
        thread_id=row["thread_id"],
        identity_id=row["identity_id"],
        identity=parse_identity(identity),
        role=row["role"],
        added_at=row["added_at"],
        added_by=parse_identity(added_by),
    )
