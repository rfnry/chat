from importlib.metadata import version as _pkg_version

__version__ = _pkg_version("rfnry-chat-server")

from rfnry_chat_protocol import (
    AssistantIdentity,
    AudioPart,
    ContentPart,
    DocumentPart,
    Event,
    EventDraft,
    FormPart,
    FormStatus,
    Identity,
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
    StreamDeltaFrame,
    StreamEndFrame,
    StreamError,
    StreamStartFrame,
    StreamTargetType,
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
    matches,
    parse_content_part,
    parse_event,
    parse_identity,
)

from rfnry_chat_server.analytics.collector import (
    AnalyticsEvent,
    AssistantAnalytics,
    OnAnalyticsCallback,
)
from rfnry_chat_server.auth import AuthenticateCallback, AuthorizeCallback, HandshakeData
from rfnry_chat_server.auth_cache import cached_authenticate
from rfnry_chat_server.broadcast.protocol import Broadcaster
from rfnry_chat_server.broadcast.recording import RecordingBroadcaster
from rfnry_chat_server.broadcast.socketio import SocketIOBroadcaster
from rfnry_chat_server.handler.context import HandlerContext
from rfnry_chat_server.handler.dispatcher import MAX_HANDLER_CHAIN_DEPTH, HandlerDispatcher
from rfnry_chat_server.handler.registry import HandlerRegistration, HandlerRegistry
from rfnry_chat_server.handler.types import HandlerCallable
from rfnry_chat_server.mentions import parse_mention_ids
from rfnry_chat_server.namespace import (
    NamespaceViolation,
    derive_namespace_path,
    parse_namespace_path,
    validate_namespace_value,
)
from rfnry_chat_server.presence import PresenceRegistry
from rfnry_chat_server.recipients import RecipientNotMemberError, normalize_recipients
from rfnry_chat_server.send import Send
from rfnry_chat_server.server import ChatServer
from rfnry_chat_server.store.memory.store import InMemoryChatStore
from rfnry_chat_server.store.postgres.store import PostgresChatStore
from rfnry_chat_server.store.protocol import ChatStore
from rfnry_chat_server.store.types import EventCursor, Page, ThreadCursor
from rfnry_chat_server.stream import Stream as Stream  # re-export

__all__ = [
    "AnalyticsEvent",
    "AssistantAnalytics",
    "AssistantIdentity",
    "AudioPart",
    "AuthenticateCallback",
    "AuthorizeCallback",
    "Broadcaster",
    "cached_authenticate",
    "ChatServer",
    "ChatStore",
    "ContentPart",
    "DocumentPart",
    "Event",
    "EventCursor",
    "EventDraft",
    "FormPart",
    "FormStatus",
    "HandshakeData",
    "Identity",
    "ImagePart",
    "InMemoryChatStore",
    "MessageEvent",
    "NamespaceViolation",
    "OnAnalyticsCallback",
    "Page",
    "PostgresChatStore",
    "PresenceRegistry",
    "ReasoningEvent",
    "RecipientNotMemberError",
    "RecordingBroadcaster",
    "Run",
    "RunCancelledEvent",
    "RunCompletedEvent",
    "RunError",
    "RunFailedEvent",
    "RunStartedEvent",
    "RunStatus",
    "SocketIOBroadcaster",
    "StreamDeltaFrame",
    "StreamEndFrame",
    "StreamError",
    "StreamStartFrame",
    "StreamTargetType",
    "SystemIdentity",
    "TenantScope",
    "TextPart",
    "Thread",
    "ThreadCreatedEvent",
    "ThreadCursor",
    "ThreadMember",
    "ThreadMemberAddedEvent",
    "ThreadMemberRemovedEvent",
    "ThreadPatch",
    "ThreadTenantChangedEvent",
    "HandlerCallable",
    "HandlerContext",
    "HandlerDispatcher",
    "HandlerRegistration",
    "HandlerRegistry",
    "MAX_HANDLER_CHAIN_DEPTH",
    "Send",
    "Stream",
    "ToolCall",
    "ToolCallEvent",
    "ToolResult",
    "ToolResultEvent",
    "UserIdentity",
    "__version__",
    "derive_namespace_path",
    "matches",
    "normalize_recipients",
    "parse_content_part",
    "parse_event",
    "parse_identity",
    "parse_mention_ids",
    "parse_namespace_path",
    "validate_namespace_value",
]
