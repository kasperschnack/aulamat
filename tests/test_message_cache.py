from __future__ import annotations

from aula_project.message_cache import MessageCache, load_message_cache, save_message_cache
from aula_project.models import MessageItem, MessageSource, MessageThread


def test_message_cache_reuses_messages_when_thread_timestamp_matches(tmp_path) -> None:
    path = tmp_path / "message-cache.json"
    cache = MessageCache()
    thread = MessageThread(
        thread_id="thread-1",
        source=MessageSource.AULA,
        last_message_at="2026-05-01T07:30:00Z",
    )
    cache.set_messages(
        thread,
        [
            MessageItem(
                message_id="message-1",
                thread_id="thread-1",
                source=MessageSource.AULA,
                sent_at="2026-05-01T07:30:00Z",
                body_text="Husk madpakke.",
            )
        ],
    )

    save_message_cache(path, cache)
    loaded = load_message_cache(path)

    messages = loaded.get_messages(thread)
    assert messages is not None
    assert [message.message_id for message in messages] == ["message-1"]
    assert messages[0].body_text == "Husk madpakke."


def test_message_cache_misses_when_thread_timestamp_changes(tmp_path) -> None:
    thread = MessageThread(
        thread_id="thread-1",
        source=MessageSource.AULA,
        last_message_at="2026-05-01T07:30:00Z",
    )
    cache = MessageCache()
    cache.set_messages(
        thread,
        [MessageItem(message_id="message-1", thread_id="thread-1", source=MessageSource.AULA)],
    )

    changed_thread = MessageThread(
        thread_id="thread-1",
        source=MessageSource.AULA,
        last_message_at="2026-05-01T08:00:00Z",
    )

    assert cache.get_messages(changed_thread) is None
