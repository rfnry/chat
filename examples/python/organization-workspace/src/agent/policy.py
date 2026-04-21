from __future__ import annotations

from typing import Any

from rfnry_chat_protocol import Identity

from src.settings import settings


def gate_reply(author: Identity) -> str | None:
    """Return a denial message if the author cannot use the agent, else None.

    Medical workspace policy: only users whose role is "manager" may ask the
    clinical reference assistant. Members can still participate in the thread
    and talk to each other — they just don't get AI responses.
    """
    if settings.WORKSPACE != "medical":
        return None
    role = _role(author)
    if role == "manager":
        return None
    return (
        f"Only managers can request clinical references from me. "
        f"{author.name}, your current role is {role!r}. "
        f"Ask a manager on your team to post the request."
    )


def author_context(author: Identity) -> str | None:
    """Return a short sentence describing the requester's tenant context,
    suitable for inclusion in an Anthropic system prompt.

    Legal workspace uses this so the model knows who is asking (name, role,
    organization, workspace) and can reference the requester in drafted
    clauses or case-law summaries.
    """
    if settings.WORKSPACE != "legal":
        return None
    metadata = author.metadata or {}
    tenant = metadata.get("tenant") if isinstance(metadata.get("tenant"), dict) else {}
    role = _role(author)
    organization = _field(tenant, "organization")
    workspace = _field(tenant, "workspace")
    return (
        f"The current requester is {author.name} "
        f"(id={author.id}, role={role}) "
        f"from organization={organization} in the {workspace} workspace. "
        f"When a drafted clause or case lookup is specific to them, "
        f"reference them by name."
    )


def _role(author: Identity) -> str:
    metadata = author.metadata or {}
    value = metadata.get("role")
    return value if isinstance(value, str) and value else "unknown"


def _field(tenant: dict[str, Any], key: str) -> str:
    value = tenant.get(key)
    return value if isinstance(value, str) and value else "unknown"
