from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from typing import Any

from aula_project.models import MessageItem, MessageThread, ThreadAssessment
from aula_project.scan_state import ScanState, utc_now_iso
from aula_project.triage import assess_thread


LEVEL_LABELS = {
    "high": "Høj",
    "medium": "Mellem",
    "low": "Lav",
}

SIGNAL_LABELS = {
    "deadline": "frist",
    "schedule_change": "ændring",
    "consent_or_form": "samtykke/formular",
    "response_requested": "svar ønsket",
    "meeting": "møde",
    "absence_or_pickup": "fravær/afhentning",
    "practical_logistics": "praktik",
    "optional_opportunity": "tilbud/aktivitet",
    "unread": "ulæst",
    "sensitive": "følsom",
    "attachments": "bilag",
}


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

    def to_text(self) -> str:
        if self.openai_review:
            summary = self.openai_review.get("summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()

        if self.new_message_count == 0:
            return "Ingen nye Aula-beskeder siden sidste gennemgang."

        message_noun = "ny Aula-besked" if self.new_message_count == 1 else "nye Aula-beskeder"
        thread_noun = "tråd" if self.new_thread_count == 1 else "tråde"
        lines = [f"{self.new_message_count} {message_noun} i {self.new_thread_count} {thread_noun}:"]
        lines.extend(_format_text_item(item) for item in _rank_text_items(self.items)[:5])
        if len(self.items) > 5:
            lines.append(f"- Og {len(self.items) - 5} flere tråde.")
        return "\n".join(lines)


def _rank_text_items(items: list[NewThreadMessages]) -> list[NewThreadMessages]:
    level_rank = {"high": 3, "medium": 2, "low": 1}
    return sorted(
        items,
        key=lambda item: (
            level_rank.get(item.deterministic_assessment.level.value, 0),
            item.deterministic_assessment.score,
            item.thread.last_message_at or "",
        ),
        reverse=True,
    )


def _format_text_item(item: NewThreadMessages) -> str:
    assessment = item.deterministic_assessment
    level = LEVEL_LABELS.get(assessment.level.value, assessment.level.value)
    title = _truncate(_single_line(item.thread.title) or "(uden titel)", 60)
    preview = _truncate(_message_preview(item), 120)
    signals = _signal_summary(item)

    parts = [f"- {level}: {title}"]
    if preview:
        parts.append(f"- {preview}")
    if signals:
        parts.append(f"({signals})")
    return " ".join(parts)


def _message_preview(item: NewThreadMessages) -> str:
    for message in item.messages:
        text = _single_line(message.body_text)
        if text:
            return text

    filenames = [
        attachment.filename
        for message in item.messages
        for attachment in message.attachments
        if attachment.filename
    ]
    if filenames:
        return "Bilag: " + ", ".join(filenames[:3])
    return ""


def _signal_summary(item: NewThreadMessages) -> str:
    labels = [
        SIGNAL_LABELS.get(signal.signal, signal.signal.replace("_", " "))
        for signal in item.deterministic_assessment.signals[:3]
    ]
    if not labels:
        return ""
    return "signaler: " + ", ".join(labels)


def _single_line(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


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
