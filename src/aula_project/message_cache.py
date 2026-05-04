from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from aula_project.models import MessageItem, MessageThread
from aula_project.normalize import normalize_messages


CACHE_VERSION = 1


@dataclass(slots=True)
class CachedThreadMessages:
    last_message_at: str
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class MessageCache:
    threads: dict[str, CachedThreadMessages] = field(default_factory=dict)

    def get_messages(self, thread: MessageThread) -> list[MessageItem] | None:
        if not thread.last_message_at:
            return None
        cached = self.threads.get(thread.thread_id)
        if cached is None or cached.last_message_at != thread.last_message_at:
            return None
        return normalize_messages(cached.messages, thread_id=thread.thread_id)

    def set_messages(self, thread: MessageThread, messages: list[MessageItem]) -> None:
        if not thread.last_message_at:
            return
        self.threads[thread.thread_id] = CachedThreadMessages(
            last_message_at=thread.last_message_at,
            messages=[message.to_dict() for message in messages],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CACHE_VERSION,
            "threads": {
                thread_id: {
                    "last_message_at": entry.last_message_at,
                    "messages": entry.messages,
                }
                for thread_id, entry in self.threads.items()
            },
        }


def load_message_cache(path: Path) -> MessageCache:
    if not path.exists():
        return MessageCache()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return MessageCache()
    if not isinstance(raw, dict) or raw.get("version") != CACHE_VERSION:
        return MessageCache()
    threads_raw = raw.get("threads")
    if not isinstance(threads_raw, dict):
        return MessageCache()

    threads: dict[str, CachedThreadMessages] = {}
    for thread_id, entry in threads_raw.items():
        if not isinstance(thread_id, str) or not isinstance(entry, dict):
            continue
        last_message_at = entry.get("last_message_at")
        messages = entry.get("messages")
        if isinstance(last_message_at, str) and isinstance(messages, list):
            threads[thread_id] = CachedThreadMessages(
                last_message_at=last_message_at,
                messages=[message for message in messages if isinstance(message, dict)],
            )
    return MessageCache(threads=threads)


def save_message_cache(path: Path, cache: MessageCache) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
