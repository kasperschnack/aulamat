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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "div", "li", "p", "tr"}:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"div", "li", "p", "tr"}:
            self._parts.append(" ")

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


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "ja"}:
            return True
        if text in {"0", "false", "no", "n", "nej", ""}:
            return False
    return bool(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, dict):
        for key in ("items", "files", "attachments", "documents"):
            nested = value.get(key)
            if isinstance(nested, Iterable) and not isinstance(nested, (str, bytes, dict)):
                return list(nested)
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _extract_text_from_html(value: str | None) -> str | None:
    if not value:
        return None
    parser = _HtmlTextExtractor()
    parser.feed(value)
    text = unescape(parser.get_text())
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


def _normalize_participants(raw: Any) -> list[str]:
    values = _as_list(_lookup(raw, "participants", "participantNames", "recipients", default=[]))

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
    unread_value = _lookup(raw, "unread", "isUnread", "hasUnreadMessages")
    if unread_value is None:
        unread_count = _lookup(raw, "unreadMessagesCount", "unread_count", default=0)
        unread_value = _normalize_bool(unread_count)

    return MessageThread(
        thread_id=_normalize_str(_lookup(raw, "thread_id", "threadId", "threadKey", "conversationId", "id"))
        or "unknown-thread",
        source=source,
        title=_normalize_str(_lookup(raw, "title", "subject", "name")),
        participants=_normalize_participants(raw),
        last_message_at=_normalize_str(
            _lookup(
                raw,
                "last_message_at",
                "lastMessageAt",
                "latestMessageTimestamp",
                "lastMessageTimestamp",
                "timestamp",
                "createdAt",
                "created",
            )
        ),
        unread=_normalize_bool(unread_value),
        preview_text=_normalize_str(
            _lookup(raw, "preview", "snippet", "latestMessageText", "latestMessage", "messagePreview")
        ),
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

    attachments_raw = _lookup(raw, "attachments", "files", "documents", default=[]) or []
    attachments = [normalize_attachment(item) for item in _as_list(attachments_raw)]
    sender = _lookup(raw, "sender", "from", "author", default=None)

    return MessageItem(
        message_id=_normalize_str(_lookup(raw, "message_id", "messageId", "messageKey", "uuid", "id"))
        or "unknown-message",
        thread_id=_normalize_str(
            _lookup(raw, "thread_id", "threadId", "threadKey", "conversationId", default=thread_id)
        )
        or "unknown-thread",
        source=infer_source(raw),
        sender_name=_normalize_str(
            _lookup(
                raw,
                "sender_name",
                "senderName",
                "fromName",
                default=_lookup(sender, "display_name", "displayName", "name", "fullName", default=sender),
            )
        ),
        sent_at=_normalize_str(_lookup(raw, "sent_at", "sentAt", "createdAt", "created", "date", "timestamp")),
        body_text=text_body,
        body_html=html_body,
        attachments=attachments,
        raw=_to_plain_data(raw) or {},
    )


def normalize_threads(raw_threads: Iterable[Any]) -> list[MessageThread]:
    return [normalize_thread(item) for item in raw_threads]


def normalize_messages(raw_messages: Iterable[Any], thread_id: str | None = None) -> list[MessageItem]:
    return [normalize_message(item, thread_id=thread_id) for item in raw_messages]
