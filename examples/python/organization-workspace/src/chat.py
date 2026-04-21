from __future__ import annotations

from rfnry_chat_server import (
    ChatServer,
    ChatStore,
    HandlerContext,
    HandlerSend,
    MessageEvent,
)


def create_chat_server(store: ChatStore, *, workspace: str) -> ChatServer:
    chat_server = ChatServer(store=store)

    @chat_server.on_message()
    async def log_message(ctx: HandlerContext, _send: HandlerSend) -> None:
        assert isinstance(ctx.event, MessageEvent)
        preview = next(
            (
                getattr(p, "text", "")
                for p in ctx.event.content
                if getattr(p, "type", None) == "text"
            ),
            "",
        )
        print(
            "msg thread=%s author=%s preview=%r",
            ctx.thread.id,
            ctx.event.author.id,
            preview[:60],
        )

    return chat_server
