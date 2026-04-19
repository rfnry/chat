from __future__ import annotations


class RecipientNotMemberError(ValueError):
    def __init__(self, identity_id: str) -> None:
        self.identity_id = identity_id
        super().__init__(f"recipient_not_member: {identity_id}")


def normalize_recipients(
    recipients: list[str] | None,
    *,
    author_id: str,
) -> list[str] | None:
    if not recipients:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for rid in recipients:
        if not isinstance(rid, str) or not rid:
            continue
        if rid == author_id:
            continue
        if rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
    return out or None
