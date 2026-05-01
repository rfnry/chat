export type {
  AssistantIdentity,
  AudioPart,
  ContentPart,
  DocumentPart,
  Event,
  EventBase,
  EventDraft,
  FormPart,
  FormStatus,
  Identity,
  IdentityRole,
  ImagePart,
  MessageEvent,
  ReasoningEvent,
  Run,
  RunCancelledEvent,
  RunCompletedEvent,
  RunError,
  RunFailedEvent,
  RunStartedEvent,
  RunStatus,
  SystemIdentity,
  TenantScope,
  TextPart,
  Thread,
  ThreadCreatedEvent,
  ThreadMember,
  ThreadMemberAddedEvent,
  ThreadMemberRemovedEvent,
  ThreadPatch,
  ThreadTenantChangedEvent,
  ToolCall,
  ToolCallEvent,
  ToolResult,
  ToolResultEvent,
  UserIdentity,
} from '@rfnry/chat-protocol'
export { matches } from '@rfnry/chat-protocol'
export { QueryClient, useQueryClient } from '@tanstack/react-query'
export {
  type AuthenticatePayload,
  ChatClient,
  type ChatClientOptions,
  type Page,
  type WithRunOptions,
  type WithRunSend,
} from './client'
export {
  ChatAuthError,
  ChatHttpError,
  SocketTransportError,
  ThreadConflictError,
  ThreadNotFoundError,
} from './errors'
export { type ChatBackfill, useChatBackfill } from './hooks/useChatBackfill'
export { useChatClient, useChatStore } from './hooks/useChatClient'
export {
  type ChatHandlers,
  type EventHandler,
  type InviteHandler,
  type MembersUpdatedHandler,
  type PresenceJoinedHandler,
  type PresenceLeftHandler,
  type RunUpdatedHandler,
  type SugarHandlerOptions,
  type ThreadUpdatedHandler,
  type UseHandlerOptions,
  useChatHandlers,
} from './hooks/useChatHandlers'
export { useChatHistory } from './hooks/useChatHistory'
export { useChatIdentity } from './hooks/useChatIdentity'
export { useChatIsWorking } from './hooks/useChatIsWorking'
export { useChatMembers } from './hooks/useChatMembers'
export {
  type ChatPresence,
  type PresenceByRole,
  useChatPresence,
} from './hooks/useChatPresence'
export {
  type ChatSession,
  type SessionStatus,
  useChatSession,
} from './hooks/useChatSession'
export { useChatStatus } from './hooks/useChatStatus'
export { useChatStreams } from './hooks/useChatStreams'
export { useChatSuspenseThread } from './hooks/useChatSuspenseThread'
export { useChatThread } from './hooks/useChatThread'
export { type UseChatThreadsOptions, useChatThreads } from './hooks/useChatThreads'
export { type TranscriptItem, useChatTranscript } from './hooks/useChatTranscript'
export { useChatWorkingDetail } from './hooks/useChatWorkingDetail'
export { ChatContext, type ChatContextValue } from './provider/ChatContext'
export { ChatProvider, type ChatProviderProps } from './provider/ChatProvider'
export {
  type ChatStore,
  type ChatStoreState,
  type ConnectionStatus,
  createChatStore,
  type StreamingItem,
} from './store/chatStore'
export { ChatStream, type StreamOptions } from './stream'
export {
  type MentionSpan,
  type ParseMemberMentionsOptions,
  type ParseMentionsResult,
  parseMemberMentions,
} from './utils/parseMentions'
export {
  type UploadItem,
  type UploadStatus,
  type UseChatUploadResult,
  useChatUpload,
} from './utils/useChatUpload'

declare const __PKG_VERSION__: string
export const VERSION: string = __PKG_VERSION__
