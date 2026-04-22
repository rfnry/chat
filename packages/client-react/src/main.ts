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
export { type AuthenticatePayload, ChatClient, type ChatClientOptions, type Page } from './client'
export {
  ChatAuthError,
  ChatHttpError,
  SocketTransportError,
  ThreadConflictError,
  ThreadNotFoundError,
} from './errors'
export { useChatClient, useChatStore, useIdentity } from './hooks/useChatClient'
export { useConnectionStatus } from './hooks/useConnectionStatus'
export { type CreateThreadInput, useCreateThread } from './hooks/useCreateThread'
export {
  type EventHandler,
  type SugarHandlerOptions,
  type UseHandlerOptions,
  useAnyEventHandler,
  useHandler,
  useMessageHandler,
  useReasoningHandler,
  useToolCallHandler,
  useToolResultHandler,
} from './hooks/useHandler'
export { type InviteHandler, useInviteHandler } from './hooks/useInviteHandler'
export { useSuspenseThread } from './hooks/useSuspenseThread'
export { type UseThreadActions, useThreadActions } from './hooks/useThreadActions'
export { useThreadActiveRuns } from './hooks/useThreadActiveRuns'
export { useThreadEvents } from './hooks/useThreadEvents'
export { useThreadIsWorking } from './hooks/useThreadIsWorking'
export { useThreadMembers } from './hooks/useThreadMembers'
export { useThreadMetadata } from './hooks/useThreadMetadata'
export {
  type SessionStatus,
  type ThreadSession,
  useThreadSession,
} from './hooks/useThreadSession'
export { type UseThreadsOptions, useThreads } from './hooks/useThreads'
export { useThreadWorkingDetail } from './hooks/useThreadWorkingDetail'
export { ChatContext, type ChatContextValue } from './provider/ChatContext'
export { ChatProvider, type ChatProviderProps } from './provider/ChatProvider'
export {
  type ChatStore,
  type ChatStoreState,
  type ConnectionStatus,
  createChatStore,
} from './store/chatStore'
export { Stream, type StreamOptions } from './stream'
export {
  type MentionSpan,
  type ParseMemberMentionsOptions,
  type ParseMentionsResult,
  parseMemberMentions,
} from './utils/parseMentions'
export {
  type UploadItem,
  type UploadStatus,
  type UseUploadResult,
  useUpload,
} from './utils/useUpload'

export const VERSION = '0.1.0-alpha.0'
