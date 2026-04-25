from __future__ import annotations

from dataclasses import dataclass

from rfnry_chat_protocol import Identity

_BOUNDARY_CHARS = set(" \t\n\r,.!?;:)]}\"'")


@dataclass(frozen=True)
class MentionSpan:
    identity_id: str
    text: str
    start: int
    length: int


@dataclass(frozen=True)
class ParsedMentions:
    recipients: list[str]
    spans: list[MentionSpan]
    body: str  # text with leading @<name> mentions stripped (see below)


def _is_boundary(ch: str | None) -> bool:
    return ch is None or ch in _BOUNDARY_CHARS


def _matches_at(text: str, pos: int, candidate: str) -> bool:
    """True if text[pos:pos+len(candidate)] equals candidate (case-insensitive)
    AND the character at pos+len(candidate) is a word boundary."""
    n = len(candidate)
    if pos + n > len(text):
        return False
    if text[pos : pos + n].lower() != candidate.lower():
        return False
    next_ch = text[pos + n] if pos + n < len(text) else None
    return _is_boundary(next_ch)


def parse_member_mentions(
    text: str,
    members: list[Identity],
    *,
    roles: list[str] | None = None,
    here_expansion: str = "matched",  # 'matched' | 'none'
) -> ParsedMentions:
    matched_members = [m for m in members if m.role in roles] if roles else list(members)

    # Longest first; tiebreak by id length DESC.
    def sort_key(m: Identity) -> tuple[int, int]:
        return (-len(m.name), -len(m.id))

    sorted_members = sorted(matched_members, key=sort_key)

    seen: set[str] = set()
    recipients: list[str] = []
    spans: list[MentionSpan] = []

    def add(identity_id: str) -> None:
        if identity_id not in seen:
            seen.add(identity_id)
            recipients.append(identity_id)

    i = 0
    while i < len(text):
        if text[i] != "@":
            i += 1
            continue
        # Boundary BEFORE @ — must be word-boundary too (so we don't match emails).
        prev_ch = text[i - 1] if i > 0 else None
        if not _is_boundary(prev_ch):
            i += 1
            continue

        cursor = i + 1
        matched = False

        # Try members (longest name first, then by id).
        for m in sorted_members:
            if _matches_at(text, cursor, m.name):
                spans.append(
                    MentionSpan(
                        identity_id=m.id,
                        text=m.name,
                        start=i,
                        length=1 + len(m.name),
                    )
                )
                add(m.id)
                i = cursor + len(m.name)
                matched = True
                break
            if _matches_at(text, cursor, m.id):
                spans.append(
                    MentionSpan(
                        identity_id=m.id,
                        text=m.id,
                        start=i,
                        length=1 + len(m.id),
                    )
                )
                add(m.id)
                i = cursor + len(m.id)
                matched = True
                break

        if matched:
            continue

        # Try @here (if enabled and members are role-filtered).
        if here_expansion == "matched" and _matches_at(text, cursor, "here"):
            for m in matched_members:
                add(m.id)
            i = cursor + len("here")
            continue

        # No match — skip the @ and keep scanning.
        i += 1

    body = _strip_leading_mentions(text, spans)
    return ParsedMentions(recipients=recipients, spans=spans, body=body)


def _strip_leading_mentions(text: str, spans: list[MentionSpan]) -> str:
    """Strip the leading contiguous run of @<name> mentions (with their
    trailing whitespace) so an agent's reply that starts '@Agent A here you
    go' becomes 'here you go' for the on-the-wire body. Only strips a
    leading run; mid-text mentions are left intact."""
    if not spans:
        return text
    # Sort spans by start.
    sorted_spans = sorted(spans, key=lambda s: s.start)  # noqa: E731
    consumed_until = 0
    # Skip leading whitespace, then look for spans starting from there.
    cursor = 0
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    span_idx = 0
    while span_idx < len(sorted_spans) and sorted_spans[span_idx].start == cursor:
        span = sorted_spans[span_idx]
        cursor = span.start + span.length
        # Skip any whitespace after the span.
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        consumed_until = cursor
        span_idx += 1
    if consumed_until == 0:
        return text
    return text[consumed_until:]
