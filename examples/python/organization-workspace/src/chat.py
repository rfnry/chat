from __future__ import annotations

import logging

from rfnry_chat_server import (
    ChatServer,
    ChatStore,
    HandlerContext,
    HandlerSend,
    MessageEvent,
)

from src.auth import authenticate
from src.settings import settings

logger = logging.getLogger(f"org.{settings.WORKSPACE}.chat")


def create_chat_server(store: ChatStore) -> ChatServer:
    chat_server = ChatServer(store=store, authenticate=authenticate)

    @chat_server.on_message()
    async def log_message(ctx: HandlerContext, _send: HandlerSend) -> None:
        assert isinstance(ctx.event, MessageEvent)
        preview = next(
            (getattr(p, "text", "") for p in ctx.event.content if getattr(p, "type", None) == "text"),
            "",
        )
        logger.info(
            "msg workspace=%s thread=%s author=%s preview=%r",
            settings.WORKSPACE,
            ctx.thread.id,
            ctx.event.author.id,
            preview[:60],
        )

    return chat_server
