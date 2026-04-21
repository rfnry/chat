from __future__ import annotations

from rfnry_chat_server import (
    ChatServer,
    ChatStore,
    HandlerContext,
    HandlerSend,
    MessageEvent,
)


def create_chat_server(store: ChatStore) -> ChatServer:
    chat_server = ChatServer(store=store)

    @chat_server.on_message()
    async def log_message(ctx: HandlerContext, _send: HandlerSend) -> None:
        assert isinstance(ctx.event, MessageEvent)
        text = next(
            (getattr(p, "text", "") for p in ctx.event.content if getattr(p, "type", None) == "text"),
            "",
        )
        print(f"msg thread={ctx.thread.id} author={ctx.event.author.id} text={text[:60]!r}")

    return chat_server
