from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from typing import Any

from aula_project.models import MessageItem, MessageThread, ThreadAssessment
from aula_project.scan_state import ScanState, utc_now_iso
from aula_project.triage import assess_thread


@dataclass(slots=True)
class NewThreadMessages:
    thread: MessageThread
    messages: list[MessageItem]
    deterministic_assessment: ThreadAssessment

    def to_openai_input(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread.thread_id,
            "title": self.thread.title,
            "participants": self.thread.participants,
            "last_message_at": self.thread.last_message_at,
            "unread": self.thread.unread,
            "deterministic_level": self.deterministic_assessment.level.value,
            "deterministic_signals": [
                signal.to_dict() for signal in self.deterministic_assessment.signals
            ],
            "messages": [
                {
                    "message_id": message.message_id,
                    "sender_name": message.sender_name,
                    "sent_at": message.sent_at,
                    "body_text": message.body_text,
                    "attachment_filenames": [
                        attachment.filename for attachment in message.attachments if attachment.filename
                    ],
                }
                for message in self.messages
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread": self.thread.to_dict(),
            "messages": [message.to_dict() for message in self.messages],
            "deterministic_assessment": self.deterministic_assessment.to_dict(),
        }


@dataclass(slots=True)
class ScheduledReviewResult:
    previous_last_checked_at: str | None
    checked_at: str
    new_thread_count: int
    new_message_count: int
    items: list[NewThreadMessages] = field(default_factory=list)
    openai_review: dict[str, Any] | None = None
    state_updated: bool = False

    def to_dict(self, *, include_messages: bool = True) -> dict[str, Any]:
        payload = {
            "previous_last_checked_at": self.previous_last_checked_at,
            "checked_at": self.checked_at,
            "new_thread_count": self.new_thread_count,
            "new_message_count": self.new_message_count,
            "state_updated": self.state_updated,
            "openai_review": self.openai_review,
        }
        if include_messages:
            payload["items"] = [item.to_dict() for item in self.items]
        else:
            payload["items"] = [
                {
                    "thread_id": item.thread.thread_id,
                    "title": item.thread.title,
                    "source": item.thread.source.value,
                    "new_message_count": len(item.messages),
                    "deterministic_level": item.deterministic_assessment.level.value,
                    "deterministic_score": item.deterministic_assessment.score,
                    "deterministic_signals": [
                        signal.to_dict() for signal in item.deterministic_assessment.signals
                    ],
                }
                for item in self.items
            ]
        return payload


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_new_message(message: MessageItem, state: ScanState, previous_checked: datetime | None) -> bool:
    if message.message_id in state.seen_message_ids:
        return False
    sent_at = _parse_timestamp(message.sent_at)
    if previous_checked is None or sent_at is None:
        return True
    return sent_at > previous_checked


def build_new_thread_messages(
    threads: list[MessageThread],
    messages_by_thread_id: dict[str, list[MessageItem]],
    state: ScanState,
) -> list[NewThreadMessages]:
    previous_checked = _parse_timestamp(state.last_checked_at)
    items: list[NewThreadMessages] = []

    for thread in threads:
        messages = messages_by_thread_id.get(thread.thread_id, [])
        new_messages = [message for message in messages if _is_new_message(message, state, previous_checked)]
        if not new_messages:
            continue
        items.append(
            NewThreadMessages(
                thread=thread,
                messages=new_messages,
                deterministic_assessment=assess_thread(thread, new_messages),
            )
        )

    return items


def mark_reviewed(state: ScanState, items: list[NewThreadMessages], *, checked_at: str | None = None) -> ScanState:
    next_state = ScanState(
        last_checked_at=checked_at or utc_now_iso(),
        seen_message_ids=set(state.seen_message_ids),
    )
    for item in items:
        for message in item.messages:
            next_state.seen_message_ids.add(message.message_id)
    return next_state


def build_openai_prompt_input(items: list[NewThreadMessages]) -> str:
    payload = {
        "task": (
            "Assess whether new Aula school messages contain something a parent should read or act on."
        ),
        "decision_guidance": [
            "Flag messages about deadlines, schedule changes, forms, consent, meetings, absence, pickup, payment, sensitive issues, or explicit response requests.",
            "Also flag optional but potentially interesting child or parent opportunities, such as camps, clubs, workshops, webinars, or enrichment activities. These are usually low priority unless there is a deadline, payment, or required action.",
            "Do not flag generic newsletters, FYI messages, or already-clear low-value chatter unless there is a concrete action or relevant logistics.",
            "Use Danish message content as primary evidence. Keep reasons short and quote only small snippets.",
        ],
        "threads": [item.to_openai_input() for item in items],
    }
    return json.dumps(payload, ensure_ascii=False)
