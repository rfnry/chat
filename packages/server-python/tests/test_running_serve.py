from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI

from rfnry_chat_server import ChatServer
from rfnry_chat_server.store.memory.store import InMemoryChatStore


def _server() -> ChatServer:
    return ChatServer(store=InMemoryChatStore())


@pytest.mark.asyncio
async def test_running_calls_start_and_stop() -> None:
    server = _server()
    assert server._watchdog_task is None

    async with server.running():
        assert server._watchdog_task is not None
        assert not server._watchdog_task.done()

    assert server._watchdog_task is None or server._watchdog_task.done()


@pytest.mark.asyncio
async def test_running_stop_runs_even_on_error() -> None:
    server = _server()
    with pytest.raises(RuntimeError, match="inside"):
        async with server.running():
            assert server._watchdog_task is not None
            raise RuntimeError("inside")

    assert server._watchdog_task is None or server._watchdog_task.done()


def test_serve_wraps_lifespan_includes_router_mounts_socketio(monkeypatch) -> None:
    server = _server()

    original_called: dict[str, bool] = {"entered": False, "exited": False}

    @asynccontextmanager
    async def original_lifespan(_app):
        original_called["entered"] = True
        try:
            yield
        finally:
            original_called["exited"] = True

    app = FastAPI(lifespan=original_lifespan)

    captured: dict[str, Any] = {}

    def fake_uvicorn_run(asgi: Any, **kwargs: Any) -> None:
        captured["asgi"] = asgi
        captured["kwargs"] = kwargs

        async def _drive() -> None:
            ctx = app.router.lifespan_context(app)
            await ctx.__aenter__()
            await ctx.__aexit__(None, None, None)

        asyncio.run(_drive())

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    server.serve(app, router_prefix="/chat", host="127.0.0.1", port=9999)

    assert captured["asgi"] is not app
    assert captured["kwargs"] == {"host": "127.0.0.1", "port": 9999}

    assert original_called["entered"] is True
    assert original_called["exited"] is True

    routes = [getattr(r, "path", None) for r in app.routes]
    assert any(p and p.startswith("/chat") for p in routes)


def test_serve_default_router_prefix_is_chat(monkeypatch) -> None:
    server = _server()
    app = FastAPI()

    def fake_uvicorn_run(*a: Any, **kw: Any) -> None:

        pass

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    server.serve(app, host="127.0.0.1", port=9999)

    routes = [getattr(r, "path", None) for r in app.routes]
    assert any(p and p.startswith("/chat") for p in routes)


def test_serve_allows_consumer_route_override(monkeypatch) -> None:

    server = _server()
    app = FastAPI()

    @app.get("/chat/threads")
    async def my_threads() -> dict[str, str]:
        return {"custom": "true"}

    def fake_uvicorn_run(*a: Any, **kw: Any) -> None:
        pass

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    server.serve(app, host="127.0.0.1", port=9999)

    threads_routes = [r for r in app.routes if getattr(r, "path", None) == "/chat/threads"]
    assert len(threads_routes) >= 1

    first = threads_routes[0]
    assert getattr(first, "endpoint", None).__name__ == "my_threads"
