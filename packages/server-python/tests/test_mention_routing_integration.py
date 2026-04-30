from __future__ import annotations

import secrets

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rfnry_chat_protocol import AssistantIdentity, Identity, UserIdentity

from rfnry_chat_server.auth import HandshakeData
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.postgres.store import PostgresChatStore


@pytest.fixture
async def setup(clean_db: asyncpg.Pool) -> tuple[AsyncClient, str]:

    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    for member_id, name in [
        ("engineer", "Engineer"),
        ("coordinator", "Coordinator"),
        ("liaison", "Liaison"),
    ]:
        ai = AssistantIdentity(id=member_id, name=name, metadata={"tenant": {"org": "A"}})
        await client.post(
            f"/chat/threads/{thread_id}/members",
            json={"identity": ai.model_dump(mode="json"), "role": "member"},
        )

    return client, thread_id


async def _post_message(client: AsyncClient, thread_id: str, text: str, **kwargs: object) -> dict:
    body = {
        "client_id": kwargs.pop("client_id", f"cid_{secrets.token_hex(4)}"),
        "content": [{"type": "text", "text": text}],
        **kwargs,
    }
    resp = await client.post(f"/chat/threads/{thread_id}/messages", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_rest_message_with_single_mention_sets_recipients(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(client, thread_id, "hi @engineer")
    assert event["recipients"] == ["engineer"]


async def test_rest_message_with_multiple_mentions(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(client, thread_id, "@engineer @coordinator review")
    assert event["recipients"] == ["engineer", "coordinator"]


async def test_rest_message_with_mention_mid_text(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(client, thread_id, "please ask @engineer about this")
    assert event["recipients"] == ["engineer"]


async def test_rest_message_with_mention_and_punctuation(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(client, thread_id, "@engineer, can you look?")
    assert event["recipients"] == ["engineer"]


async def test_rest_message_three_mentions_one_event(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    events_before = (await client.get(f"/chat/threads/{thread_id}/events")).json()
    count_before = len(events_before["items"])
    event = await _post_message(client, thread_id, "@engineer @coordinator @liaison all please look")
    assert event["recipients"] == ["engineer", "coordinator", "liaison"]
    events_after = (await client.get(f"/chat/threads/{thread_id}/events")).json()
    assert len(events_after["items"]) == count_before + 1


async def test_rest_message_without_mention_leaves_recipients_none(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(client, thread_id, "hello everyone")
    assert event["recipients"] is None


async def test_rest_message_with_explicit_recipients_not_overwritten(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(
        client,
        thread_id,
        "@engineer hi",
        recipients=["coordinator"],
    )
    assert event["recipients"] == ["coordinator"]


async def test_rest_message_with_empty_explicit_recipients_not_overwritten(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(
        client,
        thread_id,
        "@engineer hi",
        recipients=[],
    )

    assert event["recipients"] in (None, [])
    assert event["recipients"] != ["engineer"]


async def test_rest_message_with_unknown_mention_no_recipients_set(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(client, thread_id, "@nobody hi")
    assert event["recipients"] is None


async def test_rest_message_with_mixed_known_unknown(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(client, thread_id, "@engineer @nobody review")
    assert event["recipients"] == ["engineer"]


async def test_rest_message_with_name_not_id_no_match(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(client, thread_id, "@Engineer hi")
    assert event["recipients"] is None


async def test_rest_message_content_text_preserved_verbatim(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    text = "@engineer please look"
    event = await _post_message(client, thread_id, text)
    assert event["content"][0]["text"] == text


async def test_rest_message_content_with_emoji_punct_preserved(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    text = "hi @engineer 👋, can you check??"
    event = await _post_message(client, thread_id, text)
    assert event["content"][0]["text"] == text
    assert event["recipients"] == ["engineer"]


async def test_rest_message_with_id_of_non_member_no_match(clean_db: asyncpg.Pool) -> None:
    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    event = await _post_message(client, thread_id, "@engineer hi")
    assert event["recipients"] is None


async def test_rest_message_uses_member_list_at_send_time(clean_db: asyncpg.Pool) -> None:

    store = PostgresChatStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    chat_server = ChatServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.chat_server = chat_server
    app.include_router(chat_server.router, prefix="/chat")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/chat/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    msg_x = await _post_message(client, thread_id, "@engineer where are you?")
    assert msg_x["recipients"] is None

    engineer = AssistantIdentity(id="engineer", name="Engineer", metadata={"tenant": {"org": "A"}})
    await client.post(
        f"/chat/threads/{thread_id}/members",
        json={"identity": engineer.model_dump(mode="json"), "role": "member"},
    )

    events = (await client.get(f"/chat/threads/{thread_id}/events")).json()
    persisted_x = next(e for e in events["items"] if e["id"] == msg_x["id"])
    assert persisted_x["recipients"] is None

    msg_y = await _post_message(client, thread_id, "@engineer there you are")
    assert msg_y["recipients"] == ["engineer"]


async def test_rest_message_explicit_recipients_deep_equal_preserved(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    event = await _post_message(
        client,
        thread_id,
        "@engineer @liaison please all look",
        recipients=["coordinator"],
    )

    assert event["recipients"] == ["coordinator"]


async def test_member_cache_avoids_repeat_store_calls(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    for _ in range(5):
        event = await _post_message(client, thread_id, "@engineer ping")
        assert event["recipients"] == ["engineer"]


async def test_remove_member_invalidates_cache(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    first = await _post_message(client, thread_id, "@engineer hi")
    assert first["recipients"] == ["engineer"]

    resp = await client.delete(f"/chat/threads/{thread_id}/members/engineer")
    assert resp.status_code == 204

    second = await _post_message(client, thread_id, "@engineer hi again")
    assert second["recipients"] is None
