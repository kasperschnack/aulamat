from __future__ import annotations

import pytest

from aula_project.client import _review_state_for_since, _validate_since_timestamp
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


def test_review_state_for_since_replays_seen_messages_after_timestamp() -> None:
    thread = MessageThread(thread_id="thread-1", source=MessageSource.AULA)
    messages = normalize_messages(
        [
            {
                "id": "seen-but-in-window",
                "threadId": "thread-1",
                "sentAt": "2026-04-29T10:05:00Z",
                "messageText": "Husk madpakke.",
            }
        ],
        thread_id="thread-1",
    )
    saved_state = ScanState(
        last_checked_at="2026-04-29T11:00:00Z",
        seen_message_ids={"seen-but-in-window"},
    )

    items = build_new_thread_messages(
        [thread],
        {"thread-1": messages},
        _review_state_for_since(saved_state, "2026-04-29T10:00:00Z"),
    )

    assert [message.message_id for message in items[0].messages] == ["seen-but-in-window"]


def test_validate_since_timestamp_rejects_invalid_values() -> None:
    assert _validate_since_timestamp("2026-04-29T10:00:00Z") == "2026-04-29T10:00:00Z"
    with pytest.raises(ValueError, match="--since must be an ISO timestamp"):
        _validate_since_timestamp("yesterday")


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


def test_scheduled_review_result_text_prefers_openai_summary() -> None:
    result = ScheduledReviewResult(
        previous_last_checked_at=None,
        checked_at="2026-04-29T12:00:00Z",
        new_thread_count=2,
        new_message_count=3,
        openai_review={"summary": "Husk madpakke og svar på invitationen."},
    )

    assert result.to_text() == "Husk madpakke og svar på invitationen."


def test_scheduled_review_result_text_handles_no_new_messages() -> None:
    result = ScheduledReviewResult(
        previous_last_checked_at="2026-04-29T11:00:00Z",
        checked_at="2026-04-29T12:00:00Z",
        new_thread_count=0,
        new_message_count=0,
    )

    assert result.to_text() == "Ingen nye Aula-beskeder siden sidste gennemgang."


def test_scheduled_review_result_text_summarizes_deterministic_items_without_openai() -> None:
    trip_thread = MessageThread(
        thread_id="thread-1",
        source=MessageSource.AULA,
        title="Tur på fredag",
        last_message_at="2026-04-29T10:00:00Z",
    )
    gym_thread = MessageThread(
        thread_id="thread-2",
        source=MessageSource.AULA,
        title="Idræt",
        last_message_at="2026-04-29T09:00:00Z",
    )
    messages_by_thread_id = {
        "thread-1": normalize_messages(
            [
                {
                    "id": "msg-1",
                    "threadId": "thread-1",
                    "sentAt": "2026-04-29T10:00:00Z",
                    "messageText": "Svar senest fredag om jeres barn deltager.",
                }
            ],
            thread_id="thread-1",
        ),
        "thread-2": normalize_messages(
            [
                {
                    "id": "msg-2",
                    "threadId": "thread-2",
                    "sentAt": "2026-04-29T09:00:00Z",
                    "messageText": "Husk idrætstøj og drikkedunk.",
                }
            ],
            thread_id="thread-2",
        ),
    }
    items = build_new_thread_messages(
        [trip_thread, gym_thread],
        messages_by_thread_id,
        ScanState(),
    )
    result = ScheduledReviewResult(
        previous_last_checked_at=None,
        checked_at="2026-04-29T12:00:00Z",
        new_thread_count=2,
        new_message_count=2,
        items=items,
    )

    assert result.to_text() == (
        "2 nye Aula-beskeder i 2 tråde:\n"
        "- Høj: Tur på fredag - Svar senest fredag om jeres barn deltager. "
        "(signaler: frist, svar ønsket, praktik)\n"
        "- Mellem: Idræt - Husk idrætstøj og drikkedunk. (signaler: praktik)"
    )
