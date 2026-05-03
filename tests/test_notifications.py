from __future__ import annotations

from aula_project.models import MessageSource, MessageThread
from aula_project.normalize import normalize_messages
from aula_project.notifications import TerminalNotifier, build_notification_plan, send_notification
from aula_project.scan_state import ScanState
from aula_project.scheduled_review import ScheduledReviewResult, build_new_thread_messages


class RecordingNotifier:
    def __init__(self, *, succeeds: bool = True) -> None:
        self.succeeds = succeeds
        self.calls: list[tuple[str, str]] = []

    def notify(self, *, title: str, body: str) -> bool:
        self.calls.append((title, body))
        return self.succeeds


def _review_result(message_text: str) -> ScheduledReviewResult:
    thread = MessageThread(
        thread_id="thread-1",
        source=MessageSource.AULA,
        title="Tur på fredag",
    )
    messages = normalize_messages(
        [
            {
                "id": "msg-1",
                "threadId": "thread-1",
                "messageText": message_text,
            }
        ],
        thread_id="thread-1",
    )
    items = build_new_thread_messages([thread], {"thread-1": messages}, ScanState())
    return ScheduledReviewResult(
        previous_last_checked_at=None,
        checked_at="2026-04-29T12:00:00Z",
        new_thread_count=len(items),
        new_message_count=sum(len(item.messages) for item in items),
        items=items,
    )


def test_notification_plan_uses_openai_flagged_priority() -> None:
    result = _review_result("Generel orientering.")
    result.openai_review = {
        "summary": "Svar på turbeskeden.",
        "items": [
            {
                "thread_id": "thread-1",
                "flag": True,
                "priority": "high",
                "reason": "Der skal svares.",
                "recommended_action": "Svar i Aula.",
                "evidence": ["svar"],
            }
        ],
    }

    plan = build_notification_plan(result, min_priority="medium")

    assert plan.should_notify is True
    assert plan.actionable_count == 1
    assert plan.source == "openai"
    assert "Svar på turbeskeden." in plan.body
    assert "Generel orientering." in plan.body


def test_notification_plan_suppresses_openai_low_priority() -> None:
    result = _review_result("Kodning efter skole.")
    result.openai_review = {
        "summary": "Valgfrit tilbud efter skole.",
        "items": [
            {
                "thread_id": "thread-1",
                "flag": True,
                "priority": "low",
                "reason": "Valgfrit tilbud.",
                "recommended_action": "Læs hvis relevant.",
                "evidence": ["kodning"],
            }
        ],
    }

    plan = build_notification_plan(result, min_priority="medium")

    assert plan.should_notify is False
    assert plan.source == "openai"


def test_notification_plan_falls_back_to_deterministic_priority() -> None:
    result = _review_result("Svar senest fredag om jeres barn deltager.")

    plan = build_notification_plan(result, min_priority="medium")

    assert plan.should_notify is True
    assert plan.actionable_count == 1
    assert plan.source == "deterministic"
    assert "Tur på fredag" in plan.body


def test_notification_plan_includes_full_actionable_message_text() -> None:
    message_text = (
        "Svar senest fredag om jeres barn deltager. "
        "Dette er en længere besked med praktiske detaljer, som ikke skal forkortes i notifikationsvisningen."
    )
    result = _review_result(message_text)

    plan = build_notification_plan(result, min_priority="medium")

    assert message_text in plan.body
    assert "Fra: Ukendt afsender" in plan.body
    assert "..." not in plan.body


def test_send_notification_skips_when_plan_is_not_actionable() -> None:
    result = _review_result("Generel orientering.")
    plan = build_notification_plan(result, min_priority="high")
    notifier = RecordingNotifier()

    notification_result = send_notification(plan, notifier)

    assert notification_result.attempted is False
    assert notification_result.sent is False
    assert notifier.calls == []


def test_send_notification_records_delivery_result() -> None:
    result = _review_result("Svar senest fredag om jeres barn deltager.")
    plan = build_notification_plan(result, min_priority="medium")
    notifier = RecordingNotifier(succeeds=True)

    notification_result = send_notification(plan, notifier)

    assert notification_result.attempted is True
    assert notification_result.sent is True
    assert notifier.calls == [(plan.title, plan.body)]


def test_terminal_notifier_reports_availability_from_path(monkeypatch) -> None:
    monkeypatch.setattr("aula_project.notifications.shutil.which", lambda name: "/usr/local/bin/terminal-notifier")

    notifier = TerminalNotifier()

    assert TerminalNotifier.available() is True
    assert notifier.executable == "/usr/local/bin/terminal-notifier"
