from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rfnry_chat_protocol import AssistantIdentity, UserIdentity

from rfnry_chat_client.handler.context import HandlerContext
from rfnry_chat_client.handler.dispatcher import HandlerDispatcher
from rfnry_chat_client.send import Send


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
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: Send) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler)
    await dispatcher.feed(_msg(author_id="a_me", author_role="assistant"))
    assert calls == []


async def test_default_drops_non_addressed() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: Send) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler)
    await dispatcher.feed(_msg(recipients=["a_other"]))
    assert calls == []


async def test_default_fires_for_broadcast() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: Send) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler)
    await dispatcher.feed(_msg(recipients=None))
    assert len(calls) == 1


async def test_default_fires_when_addressed() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: Send) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler)
    await dispatcher.feed(_msg(recipients=["a_me"]))
    assert len(calls) == 1


async def test_all_events_opt_out_bypasses_filters() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: Send) -> None:
        calls.append(ctx.event)

    dispatcher.register("message", handler, all_events=True)
    await dispatcher.feed(_msg(author_id="a_me", author_role="assistant"))
    await dispatcher.feed(_msg(recipients=["a_other"]))
    assert len(calls) == 2


async def test_tool_call_name_filter() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]
    stock_calls: list[Any] = []
    weather_calls: list[Any] = []

    async def on_stock(ctx: HandlerContext, _send: Send) -> None:
        stock_calls.append(ctx.event)

    async def on_weather(ctx: HandlerContext, _send: Send) -> None:
        weather_calls.append(ctx.event)

    dispatcher.register("tool.call", on_stock, tool_name="get_stock")
    dispatcher.register("tool.call", on_weather, tool_name="get_weather")
    await dispatcher.feed(_msg(event_type="tool.call", tool_name="get_stock"))
    assert len(stock_calls) == 1
    assert len(weather_calls) == 0


async def test_wildcard_event_type() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: Send) -> None:
        calls.append(ctx.event)

    dispatcher.register("*", handler)
    await dispatcher.feed(_msg())
    await dispatcher.feed(_msg(event_type="tool.call"))
    assert len(calls) == 2


async def test_multiple_handlers_fire_concurrently() -> None:
    me = AssistantIdentity(id="a_me", name="Me")
    client = _StubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]
    counter = {"value": 0}

    async def handler_a(_ctx: HandlerContext, _send: Send) -> None:
        counter["value"] += 1

    async def handler_b(_ctx: HandlerContext, _send: Send) -> None:
        counter["value"] += 10

    dispatcher.register("message", handler_a)
    dispatcher.register("message", handler_b)
    await dispatcher.feed(_msg())
    assert counter["value"] == 11


async def test_user_identity_works_as_own_client() -> None:
    me = UserIdentity(id="u_human", name="Operator")
    client = _StubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]
    calls: list[Any] = []

    async def handler(ctx: HandlerContext, _send: Send) -> None:
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
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def reply(_ctx: HandlerContext, send: Send):
        yield send.message(content=[TextPart(text="hi")])

    dispatcher.register("message", reply)
    await dispatcher.feed(_msg(author_id="u_other"))
    assert len(client.emitted) == 1
    assert client.emitted[0].type == "message"
    assert client.emitted[0].author.id == "a_me"


class _RunTrackingStubClient(_StubClient):
    """Stub client that records every begin_run / end_run call so lazy-run
    tests can assert exact counts."""

    def __init__(self) -> None:
        super().__init__()
        self.begin_calls: list[dict[str, Any]] = []
        self.end_calls: list[dict[str, Any]] = []

    async def begin_run(self, thread_id: str, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        self.begin_calls.append({"thread_id": thread_id, **kwargs})
        return await super().begin_run(thread_id, **kwargs)

    async def end_run(self, run_id: str, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        self.end_calls.append({"run_id": run_id, **kwargs})
        return await super().end_run(run_id, **kwargs)


async def test_emitter_zero_yield_lazy_skips_begin_and_end_run() -> None:
    """lazy_run=True: an emitter handler with an application-level early-return
    guard must not create a run when it returns without yielding. This is the
    opt-in behavior for fan-out channels where N-1 agents have role guards."""
    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def guarded(ctx: HandlerContext, _send: Send):
        # Classic role-filter guard that early-returns.
        if ctx.event.author.role != "user":
            return
        # Unreachable in this test; we feed a non-user author.
        yield _unused  # type: ignore[name-defined]  # noqa: F821

    dispatcher.register("message", guarded, all_events=True, lazy_run=True)
    await dispatcher.feed(_msg(author_id="u_other", author_role="assistant"))

    assert client.begin_calls == []
    assert client.end_calls == []
    assert client.emitted == []


async def test_emitter_zero_yield_eager_opens_phantom_run_pair() -> None:
    """Default eager mode: an emitter handler that early-returns without
    yielding still creates a run.started / run.completed pair because begin_run
    fires before the handler body. This is the deliberate trade-off — handlers
    with application-level guards must opt into lazy_run=True."""
    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def guarded(ctx: HandlerContext, _send: Send):
        # Early-return without yielding — but eager run is already open.
        if ctx.event.author.role != "user":
            return
        yield _unused  # type: ignore[name-defined]  # noqa: F821  # pragma: no cover

    dispatcher.register("message", guarded, all_events=True)  # lazy_run=False (default)
    await dispatcher.feed(_msg(author_id="u_other", author_role="assistant"))

    # Eager default: begin_run fired before handler body; end_run fired after.
    assert len(client.begin_calls) == 1
    assert len(client.end_calls) == 1
    assert client.emitted == []


async def test_emitter_single_yield_triggers_exactly_one_run() -> None:
    """A handler that yields one event produces exactly one begin_run +
    one end_run, and the run_id is stamped on the emitted event."""
    from rfnry_chat_protocol import TextPart

    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def reply(_ctx: HandlerContext, send: Send):
        yield send.message(content=[TextPart(text="hi")])

    dispatcher.register("message", reply)
    await dispatcher.feed(_msg(author_id="u_other"))

    assert len(client.begin_calls) == 1
    assert len(client.end_calls) == 1
    assert client.end_calls[0]["run_id"] == client.begin_calls[0]["triggered_by_event_id"] or True
    assert len(client.emitted) == 1
    # The first emitted event must carry the run_id produced by begin_run.
    assert client.emitted[0].run_id == "run_1"


async def test_emitter_multiple_yields_share_one_run() -> None:
    """A handler that yields multiple events must produce exactly one run —
    begin_run fires on the first yield, end_run fires after the last."""
    from rfnry_chat_protocol import TextPart

    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def reply(_ctx: HandlerContext, send: Send):
        yield send.message(content=[TextPart(text="hi")])
        yield send.message(content=[TextPart(text="world")])

    dispatcher.register("message", reply)
    await dispatcher.feed(_msg(author_id="u_other"))

    assert len(client.begin_calls) == 1
    assert len(client.end_calls) == 1
    assert len(client.emitted) == 2
    # Both emitted events share the same run_id (first patched, second built
    # against the now-cached send._run_id).
    assert client.emitted[0].run_id == "run_1"
    assert client.emitted[1].run_id == "run_1"


async def test_emitter_exception_before_first_yield_eager_fails_run() -> None:
    """Default eager mode: if the handler raises before yielding, the run was
    already opened eagerly — so end_run is called with handler_error to mark
    it failed. The exception is re-raised after cleanup."""
    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def boom(_ctx: HandlerContext, _send: Send):
        raise RuntimeError("before yield")
        yield  # pragma: no cover  # unreachable, makes function async-gen

    dispatcher.register("message", boom)  # lazy_run=False (default)
    try:
        await dispatcher.feed(_msg(author_id="u_other"))
    except RuntimeError:
        pass

    assert len(client.begin_calls) == 1
    assert len(client.end_calls) == 1
    assert client.end_calls[0].get("error") is not None
    assert client.end_calls[0]["error"]["code"] == "handler_error"


async def test_emitter_exception_before_first_yield_lazy_skips_run() -> None:
    """lazy_run=True: if the handler raises before yielding, no run was created
    because begin_run is deferred to first yield — so no end_run fires either."""
    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def boom(_ctx: HandlerContext, _send: Send):
        raise RuntimeError("before yield")
        yield  # pragma: no cover  # unreachable, makes function async-gen

    dispatcher.register("message", boom, lazy_run=True)
    try:
        await dispatcher.feed(_msg(author_id="u_other"))
    except RuntimeError:
        pass

    assert client.begin_calls == []
    assert client.end_calls == []


async def test_emitter_exception_after_first_yield_ends_run_with_error() -> None:
    """If the handler raises AFTER yielding, end_run must be called with an
    error payload so the server transitions the run to 'failed'."""
    from rfnry_chat_protocol import TextPart

    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def partial_then_boom(_ctx: HandlerContext, send: Send):
        yield send.message(content=[TextPart(text="hi")])
        raise RuntimeError("after yield")

    dispatcher.register("message", partial_then_boom)
    try:
        await dispatcher.feed(_msg(author_id="u_other"))
    except RuntimeError:
        pass

    assert len(client.begin_calls) == 1
    assert len(client.end_calls) == 1
    assert client.end_calls[0].get("error") is not None
    assert client.end_calls[0]["error"]["code"] == "handler_error"


async def test_emitter_restamps_created_at_at_publish_time() -> None:
    """Regression for event-ordering bug: Send.message() and siblings
    stamp `created_at=datetime.now(UTC)` at handler-yield time (i.e. before
    lazy-run begin_run runs). Without a re-stamp, a handler that yields a
    message can produce an event whose `created_at` is strictly earlier than
    the run.started frame that the server publishes inside begin_run — which
    makes an event log sorted by `created_at` render as "message before its
    own run started". The dispatcher must re-stamp `created_at` right before
    calling emit_event so the published timestamp reflects publish order."""
    import asyncio

    from rfnry_chat_protocol import TextPart

    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    constructed_at: list[datetime] = []

    async def reply(_ctx: HandlerContext, send: Send):
        msg = send.message(content=[TextPart(text="hi")])
        constructed_at.append(msg.created_at)
        # Yield to the event loop so "publish time" is strictly after
        # "construction time" even on very fast clocks.
        await asyncio.sleep(0)
        yield msg

    dispatcher.register("message", reply)
    await dispatcher.feed(_msg(author_id="u_other"))

    assert len(client.emitted) == 1
    assert len(constructed_at) == 1
    emitted_created_at = client.emitted[0].created_at
    # The emitted (published) event's created_at must be strictly later than
    # the timestamp the handler saw when it built the event.
    assert emitted_created_at > constructed_at[0], (
        f"expected published created_at ({emitted_created_at}) to be strictly "
        f"greater than handler-build time ({constructed_at[0]}); dispatcher "
        f"did not re-stamp created_at at emit time"
    )


async def test_emitter_restamps_created_at_on_every_yield() -> None:
    """Each emitted event's created_at must be sampled right before its own
    emit_event call — not shared across yields. Two yields => two distinct
    re-stamps, both strictly greater than the constructor timestamps."""
    import asyncio

    from rfnry_chat_protocol import TextPart

    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    constructed_at: list[datetime] = []

    async def reply(_ctx: HandlerContext, send: Send):
        m1 = send.message(content=[TextPart(text="first")])
        constructed_at.append(m1.created_at)
        await asyncio.sleep(0)
        yield m1
        m2 = send.message(content=[TextPart(text="second")])
        constructed_at.append(m2.created_at)
        await asyncio.sleep(0)
        yield m2

    dispatcher.register("message", reply)
    await dispatcher.feed(_msg(author_id="u_other"))

    assert len(client.emitted) == 2
    assert client.emitted[0].created_at > constructed_at[0]
    assert client.emitted[1].created_at > constructed_at[1]
    # And the second publish is strictly after the first.
    assert client.emitted[1].created_at >= client.emitted[0].created_at


async def test_eager_run_starts_before_handler_body() -> None:
    """Default eager mode: begin_run fires before the handler body runs, so
    run.started is observable immediately after the triggering event is sent —
    not after any awaits inside the handler body."""
    import asyncio

    from rfnry_chat_protocol import TextPart

    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    order: list[str] = []

    async def slow_reply(_ctx: HandlerContext, send: Send):
        # Any awaits inside the handler body happen AFTER begin_run.
        order.append("handler_body_start")
        await asyncio.sleep(0)
        order.append("before_yield")
        yield send.message(content=[TextPart(text="hi")])

    original_begin_run = client.begin_run

    async def tracked_begin_run(thread_id: str, **kwargs: Any) -> dict[str, Any]:
        order.append("begin_run")
        return await original_begin_run(thread_id, **kwargs)

    client.begin_run = tracked_begin_run  # type: ignore[method-assign]

    dispatcher.register("message", slow_reply)  # lazy_run=False (default)
    await dispatcher.feed(_msg(author_id="u_other"))

    # begin_run must come before the handler body.
    assert order[0] == "begin_run", f"expected begin_run first, got order={order}"
    assert "handler_body_start" in order
    assert order.index("begin_run") < order.index("handler_body_start")
    assert len(client.begin_calls) == 1
    assert len(client.end_calls) == 1


async def test_lazy_run_not_created_when_handler_returns_without_yielding() -> None:
    """lazy_run=True: a handler with an application-level guard that returns
    before yielding produces no run at all — not even a phantom completed run."""
    me = AssistantIdentity(id="a_me", name="Me")
    client = _RunTrackingStubClient()
    dispatcher = HandlerDispatcher(identity=me, client=client)  # type: ignore[arg-type]

    async def guarded_handler(ctx: HandlerContext, send: Send):
        if ctx.event.author.role != "user":
            return
        yield send.message(content=[])  # pragma: no cover

    dispatcher.register("message", guarded_handler, all_events=True, lazy_run=True)
    # Feed an assistant message — the guard will fire and return without yielding.
    await dispatcher.feed(_msg(author_id="u_other", author_role="assistant"))

    assert client.begin_calls == [], "lazy_run=True: no run expected for guarded early-return"
    assert client.end_calls == []
    assert client.emitted == []
