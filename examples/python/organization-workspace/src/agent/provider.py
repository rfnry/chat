from __future__ import annotations

import json
import logging
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam
from rfnry_chat_protocol import Event, MessageEvent, ToolCallEvent, ToolResultEvent

from src.settings import settings

logger = logging.getLogger(f"org.{settings.WORKSPACE}.agent.provider")


def build_anthropic() -> AsyncAnthropic | None:
    if not settings.ANTHROPIC_API_KEY:
        logger.info("ANTHROPIC_API_KEY unset — provider disabled, agent will stub replies")
        return None
    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


async def call(
    anthropic: AsyncAnthropic,
    *,
    messages: list[dict[str, Any]],
    system_prompt: str,
    tools: list[dict[str, Any]],
) -> Message:
    return await anthropic.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=settings.ANTHROPIC_MAX_TOKENS,
        system=system_prompt,
        messages=cast(list[MessageParam], messages),
        tools=tools,
    )


def to_anthropic_messages(history: list[Event], assistant_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for evt in history:
        if isinstance(evt, MessageEvent):
            role = "assistant" if evt.author.id == assistant_id else "user"
            text = "".join(
                getattr(p, "text", "") for p in evt.content if getattr(p, "type", None) == "text"
            )
            if text:
                out.append({"role": role, "content": text})
        elif isinstance(evt, ToolCallEvent):
            out.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": evt.tool.id,
                            "name": evt.tool.name,
                            "input": evt.tool.arguments,
                        }
                    ],
                }
            )
        elif isinstance(evt, ToolResultEvent):
            payload = evt.tool.error if evt.tool.error is not None else evt.tool.result
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": evt.tool.id,
                            "content": json.dumps(payload, default=str),
                            "is_error": evt.tool.error is not None,
                        }
                    ],
                }
            )
    return out


def tool_result_block(*, tool_use_id: str, payload: Any, is_error: bool) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(payload, default=str),
        "is_error": is_error,
    }


def last_user_text(history: list[Event], assistant_id: str) -> str:
    for evt in reversed(history):
        if isinstance(evt, MessageEvent) and evt.author.id != assistant_id:
            for p in evt.content:
                if getattr(p, "type", None) == "text":
                    return getattr(p, "text", "")
    return ""
