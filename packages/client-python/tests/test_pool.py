import httpx
from conftest import FakeSioClient
from rfnry_chat_protocol import AssistantIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.pool import ChatClientPool
from rfnry_chat_client.transport.socket import SocketTransport


async def _noop_handler(_req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={})


async def test_pool_reuses_existing_client_for_same_url() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    constructed: list[str] = []

    def factory(base_url: str) -> ChatClient:
        constructed.append(base_url)
        sio = FakeSioClient()
        return ChatClient(
            base_url=base_url,
            identity=me,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(_noop_handler)),
            socket_transport=SocketTransport(base_url=base_url, sio_client=sio),
        )

    pool = ChatClientPool(factory=factory)
    a = await pool.get_or_connect("http://chat-a.test")
    b = await pool.get_or_connect("http://chat-a.test")
    assert a is b
    assert constructed == ["http://chat-a.test"]

    c = await pool.get_or_connect("http://chat-b.test")
    assert c is not a
    assert constructed == ["http://chat-a.test", "http://chat-b.test"]

    await pool.close_all()


async def test_pool_close_removes_entry() -> None:
    me = AssistantIdentity(id="a_me", name="Me")

    def factory(base_url: str) -> ChatClient:
        sio = FakeSioClient()
        return ChatClient(
            base_url=base_url,
            identity=me,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(_noop_handler)),
            socket_transport=SocketTransport(base_url=base_url, sio_client=sio),
        )

    pool = ChatClientPool(factory=factory)
    a1 = await pool.get_or_connect("http://chat-a.test")
    await pool.close("http://chat-a.test")
    # After close(), a fresh connect should build a NEW client for the same URL.
    a2 = await pool.get_or_connect("http://chat-a.test")
    assert a1 is not a2

    await pool.close_all()
