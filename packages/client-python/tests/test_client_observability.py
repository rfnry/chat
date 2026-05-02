from rfnry_chat_protocol import UserIdentity

from rfnry_chat_client.client import ChatClient
from rfnry_chat_client.observability import NullSink, Observability


def test_chat_client_default_observability_attached() -> None:
    client = ChatClient(base_url="http://example.invalid", identity=UserIdentity(id="u", name="u"))
    assert isinstance(client.observability, Observability)


def test_chat_client_custom_observability_attached() -> None:
    obs = Observability(sink=NullSink())
    client = ChatClient(
        base_url="http://example.invalid",
        identity=UserIdentity(id="u", name="u"),
        observability=obs,
    )
    assert client.observability is obs
