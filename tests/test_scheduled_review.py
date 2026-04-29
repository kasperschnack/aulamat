from __future__ import annotations

from aula_project.models import MessageSource, MessageThread
from aula_project.normalize import normalize_messages
from aula_project.scan_state import ScanState
from aula_project.scheduled_review import (
    ScheduledReviewResult,
    build_new_thread_messages,
    build_openai_prompt_input,
    mark_reviewed,
)


def test_build_new_thread_messages_filters_by_checkpoint_and_seen_ids() -> None:
    thread = MessageThread(
        thread_id="thread-1",
        source=MessageSource.AULA,
        title="Tur på fredag",
    )
    messages = normalize_messages(
        [
            {
                "id": "old-msg",
                "threadId": "thread-1",
                "sentAt": "2026-04-28T10:00:00Z",
                "messageText": "Gammel besked",
            },
            {
                "id": "seen-msg",
                "threadId": "thread-1",
                "sentAt": "2026-04-29T10:00:00Z",
                "messageText": "Allerede set",
            },
            {
                "id": "new-msg",
                "threadId": "thread-1",
                "sentAt": "2026-04-29T10:05:00Z",
                "messageText": "Husk madpakke til turen.",
            },
        ],
        thread_id="thread-1",
    )
    state = ScanState(
        last_checked_at="2026-04-29T09:00:00Z",
        seen_message_ids={"seen-msg"},
    )

    items = build_new_thread_messages([thread], {"thread-1": messages}, state)

    assert len(items) == 1
    assert [message.message_id for message in items[0].messages] == ["new-msg"]
    assert items[0].deterministic_assessment.score >= 3


def test_mark_reviewed_updates_checkpoint_and_seen_ids() -> None:
    thread = MessageThread(thread_id="thread-1", source=MessageSource.AULA)
    messages = normalize_messages(
        [{"id": "new-msg", "threadId": "thread-1", "messageText": "Ny besked"}],
        thread_id="thread-1",
    )
    items = build_new_thread_messages([thread], {"thread-1": messages}, ScanState())

    state = mark_reviewed(
        ScanState(last_checked_at="2026-04-28T09:00:00Z", seen_message_ids={"old-msg"}),
        items,
        checked_at="2026-04-29T11:00:00Z",
    )

    assert state.last_checked_at == "2026-04-29T11:00:00Z"
    assert state.seen_message_ids == {"old-msg", "new-msg"}


def test_openai_prompt_input_excludes_raw_payloads() -> None:
    thread = MessageThread(thread_id="thread-1", source=MessageSource.AULA, raw={"secret": "raw"})
    messages = normalize_messages(
        [
            {
                "id": "new-msg",
                "threadId": "thread-1",
                "messageText": "Svar senest fredag.",
                "rawOnly": "should stay out",
            }
        ],
        thread_id="thread-1",
    )
    items = build_new_thread_messages([thread], {"thread-1": messages}, ScanState())

    prompt = build_openai_prompt_input(items)

    assert "Svar senest fredag" in prompt
    assert "should stay out" not in prompt
    assert "secret" not in prompt


def test_scheduled_review_result_can_omit_full_messages() -> None:
    thread = MessageThread(thread_id="thread-1", source=MessageSource.AULA, title="Tur")
    messages = normalize_messages(
        [{"id": "new-msg", "threadId": "thread-1", "messageText": "Husk madpakke"}],
        thread_id="thread-1",
    )
    items = build_new_thread_messages([thread], {"thread-1": messages}, ScanState())
    result = ScheduledReviewResult(
        previous_last_checked_at=None,
        checked_at="2026-04-29T12:00:00Z",
        new_thread_count=1,
        new_message_count=1,
        items=items,
    )

    compact = result.to_dict(include_messages=False)

    assert compact["items"][0]["thread_id"] == "thread-1"
    assert compact["items"][0]["new_message_count"] == 1
    assert "messages" not in compact["items"][0]
