from __future__ import annotations

from rfnry_chat_client import ChatClient, HandlerContext, HandlerSend
from rfnry_chat_protocol import AssistantIdentity, Identity, TextPart

from src.agent_legal import provider

SYSTEM_PROMPT = (
    "You are a corporate legal advisor. Answer questions about contracts, "
    "case law, and compliance. Keep responses concise."
)


def register(chat_client: ChatClient, identity: AssistantIdentity) -> None:
    anthropic = provider.build_anthropic()

    @chat_client.on_message()
    async def respond(ctx: HandlerContext, send: HandlerSend):
        author = ctx.event.author

        history_page = await chat_client.rest.list_events(ctx.event.thread_id, limit=200)
        history = history_page["items"]
        messages = provider.to_anthropic_messages(history, identity.id)
        if not messages:
            return

        system_prompt = f"{SYSTEM_PROMPT}\n\n{_requester_context(author)}"

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
            system_prompt=system_prompt,
        )
        for block in response.content:
            text = getattr(block, "text", "")
            if getattr(block, "type", None) == "text" and text:
                yield send.message(content=[TextPart(text=text)])


def _requester_context(author: Identity) -> str:
    metadata = author.metadata or {}
    role = metadata.get("role")
    role = role if isinstance(role, str) and role else "unknown"
    tenant_raw = metadata.get("tenant")
    tenant = tenant_raw if isinstance(tenant_raw, dict) else {}
    organization = tenant.get("organization") or "unknown"
    workspace = tenant.get("workspace") or "unknown"
    return (
        f"The current requester is {author.name} (id={author.id}, role={role}) "
        f"from organization={organization} in the {workspace} workspace. "
        f"Reference them by name when appropriate."
    )
