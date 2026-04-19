from datetime import UTC, datetime

from rfnry_chat_server.analytics.collector import AnalyticsEvent, AssistantAnalytics


async def test_track_buffers_and_flush_calls_callback() -> None:
    received: list[list[AnalyticsEvent]] = []

    async def cb(batch: list[AnalyticsEvent]) -> None:
        received.append(batch)

    a = AssistantAnalytics(
        on_analytics=cb,
        thread_id="th_1",
        run_id="run_1",
        assistant_id="a1",
    )
    a.track("llm.call", {"model": "claude"})
    a.track("token.spent", {"count": 42})
    await a.flush()

    assert len(received) == 1
    assert len(received[0]) == 2
    assert received[0][0].name == "llm.call"
    assert received[0][0].thread_id == "th_1"
    assert received[0][0].timestamp <= datetime.now(UTC)


async def test_flush_with_no_callback_clears_buffer() -> None:
    a = AssistantAnalytics(on_analytics=None, thread_id="th_1", run_id="run_1", assistant_id="a1")
    a.track("foo")
    await a.flush()
    assert a._buffer == []
