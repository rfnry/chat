from __future__ import annotations

from collections.abc import Awaitable, Callable

from rfnry_chat_protocol import AssistantIdentity, Event, Identity, MessageEvent, Run, Thread, ThreadPatch

from rfnry_chat_server.analytics.collector import AssistantAnalytics
from rfnry_chat_server.store.protocol import ChatStore

InvokeAssistantCallable = Callable[[str], Awaitable[Run]]
UpdateThreadCallable = Callable[[Thread, ThreadPatch], Awaitable[Thread]]

# Window used by query_event() when walking back through thread history.
# Large enough that a user's question won't scroll out behind routine team
# chat or tool-call fan-out, small enough to keep the store query cheap.
_QUERY_LOOKBACK = 50


class HandlerContext:
    def __init__(
        self,
        store: ChatStore,
        thread: Thread,
        run: Run,
        assistant: AssistantIdentity,
        analytics: AssistantAnalytics,
        invoke_assistant: InvokeAssistantCallable | None = None,
        update_thread: UpdateThreadCallable | None = None,
    ) -> None:
        self._store = store
        self._invoke_assistant = invoke_assistant
        self._update_thread = update_thread
        self.thread = thread
        self.run = run
        self.assistant = assistant
        self.analytics = analytics

    async def events(
        self,
        limit: int | None = None,
        *,
        relevant_to_me: bool = False,
    ) -> list[Event]:
        page = await self._store.list_events(self.thread.id, limit=limit or 100)
        items = page.items
        if relevant_to_me:
            my_id = self.assistant.id
            items = [e for e in items if not e.recipients or my_id in e.recipients]
        return items

    async def members(self) -> list[Identity]:
        rows = await self._store.list_members(self.thread.id)
        return [m.identity for m in rows]

    async def invoke(self, assistant_id: str) -> Run:
        if self._invoke_assistant is None:
            raise RuntimeError("ctx.invoke is not available: no handler_resolver configured")
        return await self._invoke_assistant(assistant_id)

    async def update_thread(self, patch: ThreadPatch) -> Thread:
        """Apply a patch to the current thread atomically from within a handler.

        Writes to the store, publishes a ``thread.tenant_changed`` event if
        the tenant changed, and broadcasts the updated thread over the
        configured broadcaster (so connected clients see the change the
        same way they would if a user had PATCHed the thread via REST).

        The ``self.thread`` attribute is refreshed in place with the
        returned value, so subsequent reads like ``ctx.thread.metadata``
        reflect the update without the handler having to juggle the
        return value.

        No authorize check is performed. The handler is already running
        server-side with implicit trust — the code that calls this method
        is code you shipped, not user input. Consumers that need to
        restrict what a handler can change should enforce the rule in
        the handler body itself.

        Raises ``RuntimeError`` if the executor was constructed without
        a ``publish_thread_updated`` callback (i.e., a test harness or
        a server that isn't broadcasting thread changes).
        """
        if self._update_thread is None:
            raise RuntimeError("ctx.update_thread is not available: no update_thread callable configured")
        updated = await self._update_thread(self.thread, patch)
        self.thread = updated
        return updated

    async def query_event(self, events: list[Event] | None = None) -> MessageEvent | None:
        """Return the message event that most likely triggered this run.

        Walks thread history backwards from the most recent event and returns
        the first MessageEvent authored by ``self.run.triggered_by`` where
        ``recipients`` is either empty (broadcast) or contains
        ``self.run.assistant.id``. This is the canonical way to answer "what
        did the user just say to me" from inside a handler.

        :param events: Optional pre-fetched events list. If provided, the
            method walks this list instead of calling the store. Use this
            when the handler already needs event history for other purposes
            (history building, command routing) to avoid a redundant
            round-trip.

        Returns None if no matching message is found within the lookback
        window (``_QUERY_LOOKBACK``). Typical cause: the run was invoked
        without a preceding directed message, or the triggering message
        scrolled out behind a large volume of intervening events.
        """
        if events is None:
            events = await self.events(limit=_QUERY_LOOKBACK)
        triggerer_id = self.run.triggered_by.id
        my_id = self.assistant.id

        for evt in reversed(events):
            if not isinstance(evt, MessageEvent):
                continue
            if evt.author.id != triggerer_id:
                continue
            if evt.recipients and my_id not in evt.recipients:
                continue
            return evt
        return None
