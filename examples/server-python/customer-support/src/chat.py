from __future__ import annotations

import logging

from rfnry_chat_server import (
    ChatServer,
    ChatStore,
    HandlerContext,
    HandlerSend,
    MessageEvent,
    ToolCallEvent,
    ToolResultEvent,
)

from src.auth import authenticate
from src.observability import send_to_sink

logger = logging.getLogger("cs.server")


def create_chat_server(store: ChatStore) -> ChatServer:
    server = ChatServer(store=store, authenticate=authenticate)

    @server.on("*")
    async def handle(ctx: HandlerContext, _send: HandlerSend) -> None:
        event = ctx.event
        payload: dict[str, object] = {
            "thread_id": ctx.thread.id,
            "event_id": event.id,
            "event_type": event.type,
            "author_id": event.author.id,
            "author_role": event.author.role,
            "run_id": event.run_id,
        }
        if isinstance(event, MessageEvent):
            payload["text_preview"] = _text_preview(event)
        elif isinstance(event, ToolCallEvent):
            payload["tool_name"] = event.tool.name
        elif isinstance(event, ToolResultEvent):
            payload["tool_id"] = event.tool.id
            payload["tool_error"] = event.tool.error
        await send_to_sink("event", payload)

    return server


def _text_preview(event: MessageEvent, *, limit: int = 80) -> str:
    texts = [getattr(p, "text", "") for p in event.content if getattr(p, "type", None) == "text"]
    joined = " ".join(t for t in texts if t).strip()
    if len(joined) <= limit:
        return joined
    return joined[: limit - 1] + "…"
