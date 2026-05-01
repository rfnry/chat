# Changelog

All notable changes to `@rfnry/chat-client-react` are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-05-01

Inaugural release. Earlier `0.2.x` line was a prototype shape that has been retired; this is the first version intended for production use, on the foundation of the participant-first refactor.

### Added

- `ChatClient` — TypeScript client mirroring the Python client surface. RPC methods (`sendMessage`, `createThread`, `addMember`, `beginRun`, `endRun`, `withRun`, `joinThread`, `streamMessage`, `streamReasoning`, …) match Python naming 1:1 in camelCase.
- `<ChatProvider>` — wraps the React tree, owns the `ChatClient` + zustand store + presence slice + TanStack QueryClient.
- 16 hooks across 5 concern groups:
  - **Client + connection**: `useChatClient`, `useChatStore`, `useChatStatus`, `useChatIdentity`.
  - **Event subscription**: `useChatHandlers()` returning a stable `on.*` namespace covering `message`, `reasoning`, `toolCall`, `toolResult`, `anyEvent`, `invited`, `threadUpdated`, `membersUpdated`, `runUpdated`, `presenceJoined`, `presenceLeft`, plus generic `event(type, fn)`.
  - **Thread reads**: `useChatThreads`, `useChatThread`, `useChatSuspenseThread`, `useChatSession`.
  - **Thread content**: `useChatHistory` (persisted only), `useChatStreams` (live partials only), `useChatTranscript` (merged render-ready feed).
  - **Activity + utility**: `useChatMembers`, `useChatPresence`, `useChatIsWorking`, `useChatWorkingDetail`, `useChatUpload`.
- Render-granular subscriptions — each hook subscribes to one slice of the store; changes in one slice do not wake consumers reading another.
- Default dispatch filters — self-authored and recipient-mismatched events skipped; opt out with `{ allEvents: true }`.
- Proactive flows — provider auto-receives `thread:invited` frames, hydrates metadata, joins the room, and invalidates the threads query. Apps observe via `onThreadInvited` prop or `useChatHandlers().on.invited(fn)`.
- `ChatStream` class — token-level emitter returned by `client.streamMessage` / `streamReasoning`.
- Suspense + TanStack Query — `useChatSuspenseThread` integrates with React's Suspense boundary; `useQueryClient` and `QueryClient` re-exported.
- Typed errors — `SocketTransportError` (socket failures), `ChatHttpError` and subclasses `ThreadNotFoundError` / `ThreadConflictError` / `ChatAuthError`.
- `ChatClient.reconnect({ url?, identity?, ... })` — runtime swap of underlying transports preserving listeners.

### Tested

- 189 tests covering hook subscriptions + render isolation, handler filters, parse-once event delivery across N hooks, frame parsing for all 5 typed handler kinds, Suspense thread loading, presence hydration races, transcript composition (history + live partials interleaving), client `withRun` semantics (eager + lazy + error path), reconnect with listener restoration, upload state machine.

### Bundle

- ESM 49.61 KB / CJS 50.71 KB / DTS 18.19 KB.
