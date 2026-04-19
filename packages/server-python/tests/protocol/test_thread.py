from datetime import UTC, datetime

from rfnry_chat_server.protocol.identity import UserIdentity
from rfnry_chat_server.protocol.thread import Thread, ThreadMember, ThreadPatch


def test_thread_minimum() -> None:
    t = Thread(
        id="th_1",
        tenant={"org": "A"},
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert t.id == "th_1"
    assert t.tenant == {"org": "A"}


def test_thread_member_carries_snapshot() -> None:
    user = UserIdentity(id="u1", name="Alice")
    m = ThreadMember(
        thread_id="th_1",
        identity_id="u1",
        identity=user,
        role="member",
        added_at=datetime.now(UTC),
        added_by=user,
    )
    assert m.identity.name == "Alice"


def test_thread_patch_partial() -> None:
    p = ThreadPatch(metadata={"locked": True})
    assert p.tenant is None
    assert p.metadata == {"locked": True}
