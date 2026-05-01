from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from aula_project.scheduled_review import NewThreadMessages, ScheduledReviewResult


PRIORITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
}


class Notifier(Protocol):
    def notify(self, *, title: str, body: str) -> bool:
        pass


@dataclass(slots=True)
class NotificationPlan:
    should_notify: bool
    title: str
    body: str
    actionable_count: int
    min_priority: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_notify": self.should_notify,
            "title": self.title,
            "body": self.body,
            "actionable_count": self.actionable_count,
            "min_priority": self.min_priority,
            "source": self.source,
        }


@dataclass(slots=True)
class NotificationResult:
    plan: NotificationPlan
    attempted: bool
    sent: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "attempted": self.attempted,
            "sent": self.sent,
            "error": self.error,
        }


class AppriseNotifier:
    def __init__(self, urls: list[str]) -> None:
        if not urls:
            raise ValueError("Missing notification URL. Set AULA_NOTIFY_URL or AULA_NOTIFY_URLS.")
        self.urls = urls

    def notify(self, *, title: str, body: str) -> bool:
        try:
            import apprise
        except ImportError as exc:  # pragma: no cover - depends on optional runtime dependency
            raise RuntimeError("The 'apprise' package is not installed. Run 'uv sync'.") from exc

        notifier = apprise.Apprise()
        for url in self.urls:
            notifier.add(url)
        return bool(notifier.notify(title=title, body=body))


def build_notification_plan(
    result: ScheduledReviewResult,
    *,
    min_priority: str = "medium",
) -> NotificationPlan:
    normalized_min_priority = _normalize_priority(min_priority)
    openai_items = _openai_actionable_items(result.openai_review, min_priority=normalized_min_priority)
    if openai_items is not None:
        actionable_count = len(openai_items)
        return _build_plan(
            result,
            actionable_count=actionable_count,
            min_priority=normalized_min_priority,
            source="openai",
        )

    actionable_items = _deterministic_actionable_items(result.items, min_priority=normalized_min_priority)
    filtered_result = _filtered_result(result, actionable_items)
    return _build_plan(
        filtered_result,
        actionable_count=len(actionable_items),
        min_priority=normalized_min_priority,
        source="deterministic",
    )


def send_notification(plan: NotificationPlan, notifier: Notifier) -> NotificationResult:
    if not plan.should_notify:
        return NotificationResult(plan=plan, attempted=False, sent=False)
    try:
        sent = notifier.notify(title=plan.title, body=plan.body)
    except Exception as exc:  # pragma: no cover - exercised by integration use
        return NotificationResult(plan=plan, attempted=True, sent=False, error=str(exc))
    return NotificationResult(plan=plan, attempted=True, sent=sent)


def _build_plan(
    result: ScheduledReviewResult,
    *,
    actionable_count: int,
    min_priority: str,
    source: str,
) -> NotificationPlan:
    should_notify = actionable_count > 0
    return NotificationPlan(
        should_notify=should_notify,
        title=_notification_title(actionable_count),
        body=result.to_text() if should_notify else "Ingen vigtige nye Aula-beskeder.",
        actionable_count=actionable_count,
        min_priority=min_priority,
        source=source,
    )


def _openai_actionable_items(
    openai_review: dict[str, Any] | None,
    *,
    min_priority: str,
) -> list[dict[str, Any]] | None:
    if not isinstance(openai_review, dict):
        return None
    items = openai_review.get("items")
    if not isinstance(items, list):
        return None

    actionable: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("flag") is not True:
            continue
        priority = item.get("priority")
        if isinstance(priority, str) and _priority_at_least(priority, min_priority):
            actionable.append(item)
    return actionable


def _deterministic_actionable_items(
    items: list[NewThreadMessages],
    *,
    min_priority: str,
) -> list[NewThreadMessages]:
    return [
        item
        for item in items
        if _priority_at_least(item.deterministic_assessment.level.value, min_priority)
    ]


def _filtered_result(
    result: ScheduledReviewResult,
    items: list[NewThreadMessages],
) -> ScheduledReviewResult:
    return ScheduledReviewResult(
        previous_last_checked_at=result.previous_last_checked_at,
        checked_at=result.checked_at,
        new_thread_count=len(items),
        new_message_count=sum(len(item.messages) for item in items),
        items=items,
        openai_review=result.openai_review,
        state_updated=result.state_updated,
    )


def _notification_title(actionable_count: int) -> str:
    if actionable_count == 1:
        return "Aulamat: 1 vigtig Aula-besked"
    return f"Aulamat: {actionable_count} vigtige Aula-beskeder"


def _priority_at_least(priority: str, min_priority: str) -> bool:
    return PRIORITY_RANK[_normalize_priority(priority)] >= PRIORITY_RANK[_normalize_priority(min_priority)]


def _normalize_priority(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in PRIORITY_RANK:
        allowed = ", ".join(PRIORITY_RANK)
        raise ValueError(f"Priority must be one of: {allowed}.")
    return normalized
