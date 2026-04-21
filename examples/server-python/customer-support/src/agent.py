from __future__ import annotations

import json
import logging
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam
from rfnry_chat_client import ChatClient, HandlerContext, HandlerSend
from rfnry_chat_protocol import (
    AssistantIdentity,
    Event,
    MessageEvent,
    TextPart,
    ToolCallEvent,
    ToolResultEvent,
)

from src import tools
from src.settings import settings

logger = logging.getLogger("cs.agent")

SYSTEM_PROMPT = (
    "You are Filterbuy's customer support assistant. "
    "Answer user questions concisely. Use tools when you need order or shipping data. "
    "If you cannot resolve the request with the tools available, call escalate_to_human."
)


def build_client(base_url: str) -> ChatClient:
    identity = AssistantIdentity(id=settings.ASSISTANT_ID, name=settings.ASSISTANT_NAME)

    async def authenticate() -> dict[str, Any]:
        return {"auth": {"token": settings.ASSISTANT_TOKEN}}

    client = ChatClient(base_url=base_url, identity=identity, authenticate=authenticate)
    anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY) if settings.ANTHROPIC_API_KEY else None

    @client.on_message(in_run=True)
    async def respond(ctx: HandlerContext, send: HandlerSend):
        history_page = await client.rest.list_events(ctx.event.thread_id, limit=200)
        history = history_page["items"]
        messages = _to_anthropic(history, identity.id)
        if not messages:
            return

        if anthropic is None:
            yield send.message(
                content=[
                    TextPart(
                        text=(
                            "[stub reply — set ANTHROPIC_API_KEY to wire the real model]"
                            f" you said: {_last_user_text(history, identity.id)}"
                        )
                    )
                ]
            )
            return

        for iteration in range(1, settings.ANTHROPIC_MAX_ITERATIONS + 1):
            logger.info("llm.iter=%d thread=%s messages=%d", iteration, ctx.event.thread_id, len(messages))
            response = await anthropic.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=settings.ANTHROPIC_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=cast(list[MessageParam], messages),
                tools=tools.TOOL_DEFINITIONS,
            )

            if response.stop_reason != "tool_use":
                for block in response.content:
                    text = getattr(block, "text", "")
                    if getattr(block, "type", None) == "text" and text:
                        yield send.message(content=[TextPart(text=text)])
                return

            messages.append({"role": "assistant", "content": response.content})
            tool_blocks: list[dict[str, Any]] = []

            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                name = getattr(block, "name", "")
                args = dict(getattr(block, "input", None) or {})
                call_id = getattr(block, "id", "")

                yield send.tool_call(name=name, arguments=args, id=call_id)
                try:
                    result = await tools.execute(name, args)
                    yield send.tool_result(tool_id=call_id, result=result)
                    tool_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": json.dumps(result, default=str),
                        }
                    )
                except Exception as exc:
                    err = {"code": "tool_error", "message": f"{type(exc).__name__}: {exc}"}
                    yield send.tool_result(tool_id=call_id, error=err)
                    tool_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": json.dumps(err, default=str),
                            "is_error": True,
                        }
                    )

            messages.append({"role": "user", "content": tool_blocks})

        logger.warning("run exhausted iterations=%d", settings.ANTHROPIC_MAX_ITERATIONS)

    return client


def _to_anthropic(history: list[Event], assistant_id: str) -> list[dict[str, Any]]:
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


def _last_user_text(history: list[Event], assistant_id: str) -> str:
    for evt in reversed(history):
        if isinstance(evt, MessageEvent) and evt.author.id != assistant_id:
            for p in evt.content:
                if getattr(p, "type", None) == "text":
                    return getattr(p, "text", "")
    return ""
