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
            r"\binden\b",
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
            r"\bvikar\b",
            r"\blukket\b",
            r"\bmøder senere\b",
            r"\bfri tidligere\b",
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
            r"\bmeld tilbage\b",
            r"\bkræver handling\b",
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
            r"\blæge\b",
            r"\btandlæge\b",
        ),
        "Absence or pickup logistics language",
    ),
    (
        "practical_logistics",
        3,
        (
            r"\bkontaktbog\b",
            r"\btur\b",
            r"\bpraktisk\b",
            r"\bmadpakke\b",
            r"\bpåmindelse\b",
            r"\bhusk\b",
            r"\bmedbring\b",
            r"\bidrætstøj\b",
            r"\bbetaling\b",
        ),
        "Practical school logistics language",
    ),
    (
        "optional_opportunity",
        2,
        (
            r"\btilbud\b",
            r"\bfritidstilbud\b",
            r"\bferiecamp\b",
            r"\bsommerlejr\b",
            r"\blejr\b",
            r"\bklub\b",
            r"\bforening\b",
            r"\bkursus\b",
            r"\bworkshop\b",
            r"\bwebinar\b",
            r"\baktivitet\b",
            r"\barrangement\b",
            r"\bgratis\b",
        ),
        "Optional child or parent opportunity language",
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


def _raw_bool(raw: dict[str, object], *names: str) -> bool:
    for name in names:
        value = raw.get(name)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "y", "ja"}:
                return True
            if lowered in {"0", "false", "no", "n", "nej", ""}:
                return False
    return False


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

    sensitive = _raw_bool(thread.raw, "sensitive", "isSensitive", "confidential", "isConfidential") or any(
        _raw_bool(message.raw, "sensitive", "isSensitive", "confidential", "isConfidential") for message in messages
    )
    if sensitive:
        signals.append(
            ImportanceSignal(
                signal="sensitive",
                weight=3,
                evidence="thread or message payload is marked sensitive/confidential",
            )
        )

    requires_response = _raw_bool(
        thread.raw,
        "requiresResponse",
        "responseRequired",
        "answerRequired",
        "requiresReply",
    ) or any(
        _raw_bool(message.raw, "requiresResponse", "responseRequired", "answerRequired", "requiresReply")
        for message in messages
    )
    if requires_response and not any(signal.signal == "response_requested" for signal in signals):
        signals.append(
            ImportanceSignal(
                signal="response_requested",
                weight=3,
                evidence="thread or message payload is marked as requiring a response",
            )
        )

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
        "sensitive": sensitive,
        "requires_response": requires_response,
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
