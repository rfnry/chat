from datetime import UTC, datetime

from rfnry_chat_protocol import AssistantIdentity, Run, RunStatus, UserIdentity


def test_run_pending() -> None:
    asst = AssistantIdentity(id="a1", name="Helper")
    user = UserIdentity(id="u1", name="Alice")
    r = Run(
        id="run_1",
        thread_id="th_1",
        assistant=asst,
        triggered_by=user,
        status="pending",
        started_at=datetime.now(UTC),
    )
    assert r.completed_at is None
    assert r.error is None


def test_run_status_values() -> None:
    valid: list[RunStatus] = ["pending", "running", "completed", "failed", "cancelled"]
    assert len(valid) == 5
