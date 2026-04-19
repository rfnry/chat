export { QueryClient } from '@tanstack/react-query'
export {
  type AuthenticatePayload,
  ChatAuthError,
  ChatClient,
  type ChatClientOptions,
  ChatHttpError,
  type Page,
  ThreadConflictError,
  ThreadNotFoundError,
} from './client/ChatClient'
export { useChatClient, useChatStore } from './hooks/useChatClient'
export { useConnectionStatus } from './hooks/useConnectionStatus'
export { type CreateThreadInput, useCreateThread } from './hooks/useCreateThread'
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
export type {
  AudioPart,
  ContentPart,
  DocumentPart,
  FormPart,
  FormStatus,
  ImagePart,
  TextPart,
} from './protocol/content'
export type {
  Event,
  EventBase,
  EventDraft,
  MessageEvent,
  ReasoningEvent,
  RunCancelledEvent,
  RunCompletedEvent,
  RunFailedEvent,
  RunStartedEvent,
  ThreadCreatedEvent,
  ThreadMemberAddedEvent,
  ThreadMemberRemovedEvent,
  ThreadTenantChangedEvent,
  ToolCall,
  ToolCallEvent,
  ToolResult,
  ToolResultEvent,
} from './protocol/event'
export type {
  AssistantIdentity,
  Identity,
  IdentityRole,
  SystemIdentity,
  UserIdentity,
} from './protocol/identity'
export type { Run, RunError, RunStatus } from './protocol/run'
export type { TenantScope } from './protocol/tenant'
export { tenantMatches } from './protocol/tenant'
export type { Thread, ThreadMember, ThreadPatch } from './protocol/thread'
export { ChatContext, type ChatContextValue } from './provider/ChatContext'
export { ChatProvider, type ChatProviderProps } from './provider/ChatProvider'
export {
  type ChatStore,
  type ChatStoreState,
  type ConnectionStatus,
  createChatStore,
} from './store/chatStore'
export {
  type MentionSpan,
  type ParseMentionsResult,
  parseMentions,
} from './utils/parseMentions'
export {
  type UploadItem,
  type UploadStatus,
  type UseUploadResult,
  useUpload,
} from './utils/useUpload'

export const VERSION = '0.1.0-alpha.0'
