from __future__ import annotations

from rfnry_chat_client import ChatClient, HandlerContext, HandlerSend
from rfnry_chat_protocol import AssistantIdentity, Identity, TextPart

from src.agent_medical import provider

SYSTEM_PROMPT = (
    "You are a clinical reference assistant. Answer questions about "
    "symptoms and medications. Always recommend consulting a qualified "
    "clinician for diagnosis or treatment decisions."
)


def register(chat_client: ChatClient, identity: AssistantIdentity) -> None:
    anthropic = provider.build_anthropic()

    @chat_client.on_message()
    async def respond(ctx: HandlerContext, send: HandlerSend):
        author = ctx.event.author
        role = _role_of(author)

        if role != "manager":
            yield send.message(
                content=[
                    TextPart(
                        text=(
                            f"Only managers can request clinical references from me. "
                            f"{author.name}, your current role is {role!r}."
                        )
                    )
                ],
                recipients=[author.id],
            )
            return

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
                            f"[stub reply from {identity.name} — set ANTHROPIC_API_KEY "
                            f"to wire the real model] you said: "
                            f"{provider.last_user_text(history, identity.id)}"
                        )
                    )
                ]
            )
            return

        response = await provider.call(
            anthropic,
            messages=messages,
            system_prompt=SYSTEM_PROMPT,
        )
        for block in response.content:
            text = getattr(block, "text", "")
            if getattr(block, "type", None) == "text" and text:
                yield send.message(content=[TextPart(text=text)])


def _role_of(author: Identity) -> str:
    metadata = author.metadata or {}
    role = metadata.get("role")
    return role if isinstance(role, str) and role else "unknown"
