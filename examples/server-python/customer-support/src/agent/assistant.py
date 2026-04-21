from __future__ import annotations

import logging
from typing import Any

from rfnry_chat_client import ChatClient, HandlerContext, HandlerSend
from rfnry_chat_protocol import AssistantIdentity, TextPart

from src import tools
from src.agent import provider
from src.settings import settings

logger = logging.getLogger("cs.agent.assistant")

SYSTEM_PROMPT = (
    "You are Filterbuy's customer support assistant. "
    "Answer user questions concisely. Use tools when you need order or shipping data. "
    "If you cannot resolve the request with the tools available, call escalate_to_human."
)


def register(chat_client: ChatClient, identity: AssistantIdentity) -> None:
    anthropic = provider.build_anthropic()

    @chat_client.on_message(in_run=True)
    async def respond(ctx: HandlerContext, send: HandlerSend):
        history_page = await chat_client.rest.list_events(ctx.event.thread_id, limit=200)
        history = history_page["items"]
        messages = provider.to_anthropic_messages(history, identity.id)
        if not messages:
            return

        if anthropic is None:
            yield send.message(
                content=[
                    TextPart(
                        text=(
                            "[stub reply — set ANTHROPIC_API_KEY to wire the real model] "
                            f"you said: {provider.last_user_text(history, identity.id)}"
                        )
                    )
                ]
            )
            return

        for iteration in range(1, settings.ANTHROPIC_MAX_ITERATIONS + 1):
            logger.info(
                "llm.iter=%d thread=%s messages=%d",
                iteration,
                ctx.event.thread_id,
                len(messages),
            )
            response = await provider.call(
                anthropic,
                messages=messages,
                system_prompt=SYSTEM_PROMPT,
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
                        provider.tool_result_block(
                            tool_use_id=call_id, payload=result, is_error=False
                        )
                    )
                except Exception as exc:
                    err = {"code": "tool_error", "message": f"{type(exc).__name__}: {exc}"}
                    yield send.tool_result(tool_id=call_id, error=err)
                    tool_blocks.append(
                        provider.tool_result_block(
                            tool_use_id=call_id, payload=err, is_error=True
                        )
                    )

            messages.append({"role": "user", "content": tool_blocks})

        logger.warning("run exhausted iterations=%d", settings.ANTHROPIC_MAX_ITERATIONS)
