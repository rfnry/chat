from __future__ import annotations

import os
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam
from rfnry_chat_protocol import Event, MessageEvent

ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
ANTHROPIC_MAX_TOKENS = 2048


def build_anthropic() -> AsyncAnthropic | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY unset — provider disabled, agent will stub replies")
        return None
    return AsyncAnthropic(api_key=api_key)


async def call(
    anthropic: AsyncAnthropic,
    *,
    messages: list[dict[str, Any]],
    system_prompt: str,
) -> Message:
    return await anthropic.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=ANTHROPIC_MAX_TOKENS,
        system=system_prompt,
        messages=cast(list[MessageParam], messages),
    )


def to_anthropic_messages(history: list[Event], assistant_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for evt in history:
        if not isinstance(evt, MessageEvent):
            continue
        role = "assistant" if evt.author.id == assistant_id else "user"
        text = "".join(
            getattr(p, "text", "") for p in evt.content if getattr(p, "type", None) == "text"
        )
        if text:
            out.append({"role": role, "content": text})
    return out


def last_user_text(history: list[Event], assistant_id: str) -> str:
    for evt in reversed(history):
        if isinstance(evt, MessageEvent) and evt.author.id != assistant_id:
            for p in evt.content:
                if getattr(p, "type", None) == "text":
                    return getattr(p, "text", "")
    return ""
