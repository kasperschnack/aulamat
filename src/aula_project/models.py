from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any


class MessageSource(str, Enum):
    AULA = "aula"
    OVERBLIK = "overblik"
    MEEBOOK = "meebook"
    UNKNOWN = "unknown"


class ImportanceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


@dataclass(slots=True)
class JsonModel:
    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class ChildContext(JsonModel):
    child_id: str
    display_name: str | None = None
    institution_id: str | None = None
    institution_name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Profile(JsonModel):
    profile_id: str
    display_name: str | None = None
    role: str | None = None
    children: list[ChildContext] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Attachment(JsonModel):
    attachment_id: str
    filename: str | None = None
    content_type: str | None = None
    url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MessageThread(JsonModel):
    thread_id: str
    source: MessageSource
    title: str | None = None
    participants: list[str] = field(default_factory=list)
    last_message_at: str | None = None
    unread: bool = False
    preview_text: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MessageItem(JsonModel):
    message_id: str
    thread_id: str
    source: MessageSource
    sender_name: str | None = None
    sent_at: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuthCacheStatus(JsonModel):
    cache_path: str
    cache_exists: bool
    cached_at: str | None = None
    access_token_expires_at: str | None = None
    access_token_expires_at_local: str | None = None
    local_timezone: str | None = None
    access_token_valid_for_seconds: int | None = None
    access_token_reusable: bool = False
    refresh_token_present: bool = False
    cookie_count: int = 0
    session_cookie_names: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuthResult(JsonModel):
    strategy: str
    cache: AuthCacheStatus


@dataclass(slots=True)
class ImportanceSignal(JsonModel):
    signal: str
    weight: int
    evidence: str


@dataclass(slots=True)
class ThreadAssessment(JsonModel):
    thread: MessageThread
    messages: list[MessageItem] = field(default_factory=list)
    level: ImportanceLevel = ImportanceLevel.LOW
    score: int = 0
    signals: list[ImportanceSignal] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
