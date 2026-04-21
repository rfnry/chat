from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rfnry_chat_protocol import AssistantIdentity, UserIdentity

from rfnry_chat_client.dispatch import Dispatcher
from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.handler.send import HandlerSend


class _StubClient:
    def __init__(self) -> None:
        self.emitted: list[Any] = []
        self.runs: list[str] = []
        self._next_run_id = 0

    async def emit_event(self, event: Any) -> Any:
        self.emitted.append(event)
        return event

    @property
    def socket(self) -> Any:
        return self

    async def begin_run(self, _thread_id: str, **_kwargs: Any) -> dict[str, Any]:
        self._next_run_id += 1
        run_id = f"run_{self._next_run_id}"
        self.runs.append(run_id)
        return {"run_id": run_id, "status": "running"}

    async def end_run(self, run_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"run_id": run_id, "status": "completed"}


def _msg(
    *,
    author_id: str = "u_1",
    author_role: str = "user",
    recipients: list[str] | None = None,
    tool_name: str | None = None,
    event_type: str = "message",
) -> dict[str, Any]:
    author = {"role": author_role, "id": author_id, "name": author_id, "metadata": {}}
    now = datetime.now(UTC).isoformat()
    base: dict[str, Any] = {
        "id": "evt_1",
        "thread_id": "t_1",
        "run_id": None,
        "author": author,
        "created_at": now,
        "metadata": {},
        "client_id": None,
        "recipients": recipients,
        "type": event_type,
    }
    if event_type == "message":
        base["content"] = [{"type": "text", "text": "hi"}]
    if event_type == "tool.call":
        base["tool"] = {"id": "c_1", "name": tool_name or "f", "arguments": {}}
    if event_type == "tool.result":
        base["tool"] = {"id": "c_1", "result": {"ok": True}}
    return base


async def test_default_drops_self_authored() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: HandlerSend) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler)
    await dispatcher.feed(_msg(author_id="a_me", author_role="assistant"))
    assert calls == []


async def test_default_drops_non_addressed() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: HandlerSend) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler)
    await dispatcher.feed(_msg(recipients=["a_other"]))
    assert calls == []


async def test_default_fires_for_broadcast() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: HandlerSend) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler)
    await dispatcher.feed(_msg(recipients=None))
    assert len(calls) == 1


async def test_default_fires_when_addressed() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: HandlerSend) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler)
    await dispatcher.feed(_msg(recipients=["a_me"]))
    assert len(calls) == 1


async def test_all_events_opt_out_bypasses_filters() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: HandlerSend) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler, all_events=True)
    await dispatcher.feed(_msg(author_id="a_me", author_role="assistant"))
    await dispatcher.feed(_msg(recipients=["a_other"]))
    assert len(calls) == 2


async def test_tool_call_name_filter() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]
    stock_calls: list[Any] = []
    weather_calls: list[Any] = []

    async def on_stock(ctx: HandlerContext, _send: HandlerSend) -> None:
        stock_calls.append(ctx.event)

    async def on_weather(ctx: HandlerContext, _send: HandlerSend) -> None:
        weather_calls.append(ctx.event)

    dispatcher.register("tool.call", on_stock, tool_name="get_stock")
    dispatcher.register("tool.call", on_weather, tool_name="get_weather")
    await dispatcher.feed(_msg(event_type="tool.call", tool_name="get_stock"))
    assert len(stock_calls) == 1
    assert len(weather_calls) == 0


async def test_wildcard_event_type() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: HandlerSend) -> None:
        calls.append(ctx.event)

    dispatcher.register("*", handler)
    await dispatcher.feed(_msg())
    await dispatcher.feed(_msg(event_type="tool.call"))
    assert len(calls) == 2


async def test_multiple_handlers_fire_concurrently() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]
    counter = {"value": 0}

    async def handler_a(_ctx: HandlerContext, _send: HandlerSend) -> None:
        counter["value"] += 1

    async def handler_b(_ctx: HandlerContext, _send: HandlerSend) -> None:
        counter["value"] += 10

    dispatcher.register("message", handler_a)
    dispatcher.register("message", handler_b)
    await dispatcher.feed(_msg())
    assert counter["value"] == 11


async def test_user_identity_works_as_own_client() -> None:
    me = UserIdentity(id="u_human", name="Operator")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: HandlerSend) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler)
    await dispatcher.feed(_msg(author_id="u_human", author_role="user"))
    assert calls == []
    await dispatcher.feed(_msg(author_id="u_other", recipients=["u_human"]))
    assert len(calls) == 1


async def test_emitter_handler_publishes_via_client() -> None:
    from rfnry_chat_protocol import TextPart

    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = Dispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def reply(_ctx: HandlerContext, send: HandlerSend):
        yield send.message(content=[TextPart(text="hi")])

    dispatcher.register("message", reply)
    await dispatcher.feed(_msg(author_id="u_other"))
    assert len(client.emitted) == 1
    assert client.emitted[0].type == "message"
    assert client.emitted[0].author.id == "a_me"
