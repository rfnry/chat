from __future__ import annotations

from collections.abc import Iterable

from rfnry_chat_protocol import ContentPart

_TRAILING_PUNCT = ",.!?;:)]}'\""


def parse_mention_ids(text: str, member_ids: set[str]) -> list[str]:

    seen: set[str] = set()
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "@":
            i += 1
            continue
        j = i + 1
        while j < n and not text[j].isspace():
            j += 1
        token = text[i + 1 : j]
        while token and token[-1] in _TRAILING_PUNCT:
            token = token[:-1]
        if token and token in member_ids and token not in seen:
            seen.add(token)
            out.append(token)
        i = j if j > i else i + 1
    return out


def extract_text(content: Iterable[ContentPart]) -> str:

    parts: list[str] = []
    for p in content:
        if getattr(p, "type", None) == "text":
            parts.append(getattr(p, "text", ""))
    return "\n".join(parts)
