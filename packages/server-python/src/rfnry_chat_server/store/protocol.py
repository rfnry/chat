from __future__ import annotations

from typing import Protocol

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
)

from rfnry_chat_server.store.types import EventCursor, Page, ThreadCursor


class ChatStore(Protocol):
    async def create_thread(self, thread: Thread) -> Thread: ...
    async def get_thread(self, thread_id: str) -> Thread | None: ...
    async def list_threads(
        self,
        tenant_filter: TenantScope,
        cursor: ThreadCursor | None = None,
        limit: int = 50,
    ) -> Page[Thread]: ...
    async def update_thread(self, thread_id: str, patch: ThreadPatch) -> Thread: ...
    async def delete_thread(self, thread_id: str) -> None: ...

    async def append_event(self, event: Event) -> Event: ...
    async def list_events(
        self,
        thread_id: str,
        since: EventCursor | None = None,
        until: EventCursor | None = None,
        limit: int = 100,
        types: list[str] | None = None,
    ) -> Page[Event]: ...
    async def get_event(self, event_id: str) -> Event | None: ...

    async def create_run(self, run: Run) -> Run: ...
    async def get_run(self, run_id: str) -> Run | None: ...
    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        error: RunError | None = None,
    ) -> Run: ...
    async def find_run_by_idempotency_key(self, thread_id: str, key: str) -> Run | None: ...
    async def find_active_run(self, thread_id: str, assistant_id: str) -> Run | None: ...

    async def add_member(
        self,
        thread_id: str,
        identity: Identity,
        added_by: Identity,
        role: str = "member",
    ) -> ThreadMember: ...
    async def remove_member(self, thread_id: str, identity_id: str) -> None: ...
    async def list_members(self, thread_id: str) -> list[ThreadMember]: ...
    async def is_member(self, thread_id: str, identity_id: str) -> bool: ...
