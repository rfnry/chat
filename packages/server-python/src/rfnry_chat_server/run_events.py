from __future__ import annotations

import secrets
from datetime import UTC, datetime

from rfnry_chat_protocol import (
    Identity,
    Run,
    RunCancelledEvent,
    RunCompletedEvent,
    RunError,
    RunFailedEvent,
    RunStartedEvent,
    Thread,
)


def run_started(run: Run, thread: Thread, actor: Identity) -> RunStartedEvent:
    return RunStartedEvent(
        id=_evt_id(),
        thread_id=thread.id,
        run_id=run.id,
        author=actor,
        created_at=datetime.now(UTC),
    )


def run_completed(run: Run, thread: Thread, actor: Identity) -> RunCompletedEvent:
    return RunCompletedEvent(
        id=_evt_id(),
        thread_id=thread.id,
        run_id=run.id,
        author=actor,
        created_at=datetime.now(UTC),
    )


def run_cancelled(run: Run, thread: Thread, actor: Identity) -> RunCancelledEvent:
    return RunCancelledEvent(
        id=_evt_id(),
        thread_id=thread.id,
        run_id=run.id,
        author=actor,
        created_at=datetime.now(UTC),
    )


def run_failed(
    run: Run,
    thread: Thread,
    actor: Identity,
    err: RunError,
) -> RunFailedEvent:
    return RunFailedEvent.model_validate(
        {
            "id": _evt_id(),
            "thread_id": thread.id,
            "run_id": run.id,
            "author": actor.model_dump(mode="json"),
            "created_at": datetime.now(UTC),
            "type": "run.failed",
            "error": {"code": err.code, "message": err.message},
        }
    )


def _evt_id() -> str:
    return f"evt_{secrets.token_hex(8)}"
