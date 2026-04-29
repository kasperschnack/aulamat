from __future__ import annotations

from collections.abc import Iterable
from html import unescape
from html.parser import HTMLParser
import re
from typing import Any

from aula_project.models import Attachment, ChildContext, MessageItem, MessageSource, MessageThread, Profile


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _to_plain_data(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _to_plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain_data(item) for item in value]
    if hasattr(value, "model_dump"):
        return _to_plain_data(value.model_dump())
    if hasattr(value, "__dict__"):
        data = {key: val for key, val in vars(value).items() if not key.startswith("_")}
        return _to_plain_data(data)
    return repr(value)


def _lookup(raw: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(raw, dict) and name in raw:
            return raw[name]
        if hasattr(raw, name):
            return getattr(raw, name)
    return default


def _normalize_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_text_from_html(value: str | None) -> str | None:
    if not value:
        return None
    parser = _HtmlTextExtractor()
    parser.feed(value)
    text = unescape(parser.get_text())
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


def _normalize_participants(raw: Any) -> list[str]:
    values = _lookup(raw, "participants", "participantNames", default=[])
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return []

    names: list[str] = []
    for item in values:
        name = _normalize_str(
            _lookup(item, "display_name", "displayName", "name", "fullName", default=item)
        )
        if name:
            names.append(name)
    return names


def infer_source(raw: Any) -> MessageSource:
    search_space = " ".join(
        filter(
            None,
            [
                _normalize_str(_lookup(raw, "source")),
                _normalize_str(_lookup(raw, "provider")),
                _normalize_str(_lookup(raw, "integration")),
                _normalize_str(_lookup(raw, "widget")),
                _normalize_str(_lookup(raw, "title")),
                _normalize_str(_lookup(raw, "subject")),
            ],
        )
    ).lower()
    if "overblik" in search_space:
        return MessageSource.OVERBLIK
    if "meebook" in search_space:
        return MessageSource.MEEBOOK
    if search_space:
        return MessageSource.AULA
    return MessageSource.UNKNOWN


def normalize_child_context(raw: Any) -> ChildContext:
    return ChildContext(
        child_id=_normalize_str(_lookup(raw, "id", "childId")) or "unknown-child",
        display_name=_normalize_str(_lookup(raw, "display_name", "displayName", "name")),
        institution_id=_normalize_str(_lookup(raw, "institution_id", "institutionId")),
        institution_name=_normalize_str(_lookup(raw, "institution_name", "institutionName")),
        raw=_to_plain_data(raw) or {},
    )


def normalize_profile(raw: Any) -> Profile:
    children_raw = _lookup(raw, "children", default=[]) or []
    children = [normalize_child_context(item) for item in children_raw]
    return Profile(
        profile_id=_normalize_str(_lookup(raw, "id", "profileId", "profile_id")) or "unknown-profile",
        display_name=_normalize_str(_lookup(raw, "display_name", "displayName", "name")),
        role=_normalize_str(_lookup(raw, "role")),
        children=children,
        raw=_to_plain_data(raw) or {},
    )


def normalize_attachment(raw: Any) -> Attachment:
    return Attachment(
        attachment_id=_normalize_str(_lookup(raw, "id", "attachmentId", "fileId")) or "unknown-attachment",
        filename=_normalize_str(_lookup(raw, "filename", "fileName", "title", "name")),
        content_type=_normalize_str(_lookup(raw, "content_type", "contentType", "mimeType")),
        url=_normalize_str(_lookup(raw, "url", "downloadUrl", "href")),
        raw=_to_plain_data(raw) or {},
    )


def normalize_thread(raw: Any) -> MessageThread:
    source = infer_source(raw)
    unread_value = _lookup(raw, "unread", "isUnread")
    if unread_value is None:
        unread_count = _lookup(raw, "unreadMessagesCount", "unread_count", default=0)
        unread_value = bool(unread_count)

    return MessageThread(
        thread_id=_normalize_str(_lookup(raw, "thread_id", "threadId", "id")) or "unknown-thread",
        source=source,
        title=_normalize_str(_lookup(raw, "title", "subject")),
        participants=_normalize_participants(raw),
        last_message_at=_normalize_str(
            _lookup(
                raw,
                "last_message_at",
                "lastMessageAt",
                "latestMessageTimestamp",
                "timestamp",
                "createdAt",
            )
        ),
        unread=bool(unread_value),
        preview_text=_normalize_str(_lookup(raw, "preview", "snippet", "latestMessageText")),
        raw=_to_plain_data(raw) or {},
    )


def normalize_message(raw: Any, thread_id: str | None = None) -> MessageItem:
    html_body = _normalize_str(
        _lookup(raw, "body_html", "bodyHtml", "html", "messageHtml", "content_html", "contentHtml")
    )
    text_body = _normalize_str(
        _lookup(raw, "body_text", "bodyText", "text", "message", "messageText", "content")
    )
    if not text_body:
        text_body = _extract_text_from_html(html_body)

    attachments_raw = _lookup(raw, "attachments", default=[]) or []
    attachments = [normalize_attachment(item) for item in attachments_raw]

    return MessageItem(
        message_id=_normalize_str(_lookup(raw, "message_id", "messageId", "id")) or "unknown-message",
        thread_id=_normalize_str(_lookup(raw, "thread_id", "threadId", default=thread_id)) or "unknown-thread",
        source=infer_source(raw),
        sender_name=_normalize_str(
            _lookup(raw, "sender_name", "senderName", "fromName", default=_lookup(raw, "sender"))
        ),
        sent_at=_normalize_str(_lookup(raw, "sent_at", "sentAt", "createdAt", "timestamp")),
        body_text=text_body,
        body_html=html_body,
        attachments=attachments,
        raw=_to_plain_data(raw) or {},
    )


def normalize_threads(raw_threads: Iterable[Any]) -> list[MessageThread]:
    return [normalize_thread(item) for item in raw_threads]


def normalize_messages(raw_messages: Iterable[Any], thread_id: str | None = None) -> list[MessageItem]:
    return [normalize_message(item, thread_id=thread_id) for item in raw_messages]
