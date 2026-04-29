from __future__ import annotations

from collections.abc import Iterable
import re

from aula_project.models import ImportanceLevel, ImportanceSignal, MessageItem, MessageThread, ThreadAssessment


SIGNAL_RULES = (
    (
        "deadline",
        4,
        (
            r"\bdeadline\b",
            r"\bfrist\b",
            r"\bsenest\b",
            r"\btilmeld(?:ing)?\b",
            r"\baflever(?:ing|es)?\b",
        ),
        "Deadline or due-date language",
    ),
    (
        "schedule_change",
        4,
        (
            r"\baflyst\b",
            r"\bændret\b",
            r"\brykket\b",
            r"\bny tid\b",
            r"\bomlagt\b",
        ),
        "Schedule-change language",
    ),
    (
        "consent_or_form",
        4,
        (
            r"\bsamtykke\b",
            r"\bblanket\b",
            r"\bformular\b",
            r"\bunderskrift\b",
            r"\btilladelse\b",
        ),
        "Consent or form language",
    ),
    (
        "response_requested",
        3,
        (
            r"\bsvar(?:\s+gerne|\s+senest)?\b",
            r"\btilbagemelding\b",
            r"\bgiv besked\b",
            r"\bbesvar\b",
        ),
        "Response-request language",
    ),
    (
        "meeting",
        3,
        (
            r"\bmøde\b",
            r"\bforældremøde\b",
            r"\bskole-hjem-samtale\b",
            r"\bsamtale\b",
        ),
        "Meeting-related language",
    ),
    (
        "absence_or_pickup",
        3,
        (
            r"\bfravær\b",
            r"\bsyg\b",
            r"\bhent(?:e|ning)\b",
            r"\bafhentning\b",
            r"\baflevering\b",
        ),
        "Absence or pickup logistics language",
    ),
    (
        "practical_logistics",
        2,
        (
            r"\bkontaktbog\b",
            r"\btur\b",
            r"\bpraktisk\b",
            r"\bmadpakke\b",
            r"\bpåmindelse\b",
        ),
        "Practical school logistics language",
    ),
)


def _message_texts(messages: Iterable[MessageItem]) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for message in messages:
        if message.body_text:
            label = f"message {message.message_id}"
            if message.sender_name:
                label += f" from {message.sender_name}"
            texts.append((label, message.body_text))
    return texts


def _find_match(patterns: tuple[str, ...], sources: list[tuple[str, str]]) -> str | None:
    for source_name, text in sources:
        lowered = text.lower()
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                return f'{source_name}: matched "{match.group(0)}"'
    return None


def _importance_level(score: int) -> ImportanceLevel:
    if score >= 6:
        return ImportanceLevel.HIGH
    if score >= 3:
        return ImportanceLevel.MEDIUM
    return ImportanceLevel.LOW


def assess_thread(thread: MessageThread, messages: list[MessageItem]) -> ThreadAssessment:
    signals: list[ImportanceSignal] = []
    text_sources: list[tuple[str, str]] = []

    if thread.title:
        text_sources.append(("thread title", thread.title))
    if thread.preview_text:
        text_sources.append(("thread preview", thread.preview_text))
    text_sources.extend(_message_texts(messages))

    for signal_name, weight, patterns, description in SIGNAL_RULES:
        evidence = _find_match(patterns, text_sources)
        if evidence:
            signals.append(ImportanceSignal(signal=signal_name, weight=weight, evidence=f"{description}; {evidence}"))

    if thread.unread:
        signals.append(ImportanceSignal(signal="unread", weight=2, evidence="thread.unread is true"))

    attachment_count = sum(len(message.attachments) for message in messages)
    if attachment_count:
        noun = "attachment" if attachment_count == 1 else "attachments"
        signals.append(
            ImportanceSignal(
                signal="attachments",
                weight=1,
                evidence=f"thread contains {attachment_count} {noun}",
            )
        )

    score = sum(signal.weight for signal in signals)
    facts = {
        "thread_id": thread.thread_id,
        "unread": thread.unread,
        "message_count": len(messages),
        "attachment_count": attachment_count,
        "participants": thread.participants,
        "last_message_at": thread.last_message_at,
    }
    return ThreadAssessment(
        thread=thread,
        messages=messages,
        level=_importance_level(score),
        score=score,
        signals=signals,
        facts=facts,
    )


def rank_threads(assessments: Iterable[ThreadAssessment], *, include_low: bool = False) -> list[ThreadAssessment]:
    filtered = [
        assessment
        for assessment in assessments
        if include_low or assessment.level in (ImportanceLevel.MEDIUM, ImportanceLevel.HIGH)
    ]
    return sorted(
        filtered,
        key=lambda assessment: (
            assessment.score,
            assessment.thread.unread,
            assessment.thread.last_message_at or "",
        ),
        reverse=True,
    )
