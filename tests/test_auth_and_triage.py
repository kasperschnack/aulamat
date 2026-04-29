from __future__ import annotations

import json
from pathlib import Path

from aula_project.auth import inspect_token_cache
from aula_project.models import ImportanceLevel
from aula_project.normalize import normalize_messages, normalize_threads
from aula_project.triage import assess_thread, rank_threads


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_inspect_token_cache_reports_reusable_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aula_project.auth.time.time", lambda: 1700000000.0)
    cache_path = tmp_path / "tokens.json"
    cache_path.write_text((FIXTURES_DIR / "auth_cache.json").read_text(encoding="utf-8"), encoding="utf-8")

    status = inspect_token_cache(cache_path)

    assert status.cache_exists is True
    assert status.access_token_reusable is True
    assert status.refresh_token_present is True
    assert status.access_token_valid_for_seconds == 3600
    assert status.session_cookie_names == ["SimpleSAML", "AUTH_SESSION_ID", "KEYCLOAK_SESSION"]


def test_inspect_token_cache_marks_expired_access_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aula_project.auth.time.time", lambda: 1700003700.0)
    cache_path = tmp_path / "tokens.json"
    cache_path.write_text((FIXTURES_DIR / "auth_cache.json").read_text(encoding="utf-8"), encoding="utf-8")

    status = inspect_token_cache(cache_path)

    assert status.access_token_reusable is False
    assert status.refresh_token_present is True
    assert status.access_token_valid_for_seconds == -100


def test_assess_thread_flags_meeting_and_unread_signals() -> None:
    thread = normalize_threads(_load_fixture("message_threads.json"))[0]
    messages = normalize_messages(_load_fixture("thread_messages_thread-1.json"), thread_id=thread.thread_id)

    assessment = assess_thread(thread, messages)

    assert assessment.level is ImportanceLevel.HIGH
    assert assessment.score >= 6
    assert {signal.signal for signal in assessment.signals} >= {
        "meeting",
        "unread",
        "attachments",
    }


def test_rank_threads_filters_low_priority_threads() -> None:
    threads = normalize_threads(_load_fixture("message_threads.json"))
    high = assess_thread(
        threads[0],
        normalize_messages(_load_fixture("thread_messages_thread-1.json"), thread_id=threads[0].thread_id),
    )
    low = assess_thread(threads[1], [])

    ranked = rank_threads([low, high])

    assert [assessment.thread.thread_id for assessment in ranked] == ["thread-1"]


def test_assess_thread_uses_payload_response_and_sensitive_flags() -> None:
    thread = normalize_threads(
        [
            {
                "id": "thread-sensitive",
                "subject": "Kort info",
                "responseRequired": True,
                "isSensitive": "true",
            }
        ]
    )[0]
    messages = normalize_messages(
        [
            {
                "id": "msg-sensitive",
                "content_html": "<p>Se venligst beskeden.</p>",
            }
        ],
        thread_id=thread.thread_id,
    )

    assessment = assess_thread(thread, messages)

    assert assessment.level is ImportanceLevel.HIGH
    assert {signal.signal for signal in assessment.signals} >= {"response_requested", "sensitive"}
    assert assessment.facts["requires_response"] is True
    assert assessment.facts["sensitive"] is True


def test_assess_thread_flags_practical_danish_school_language() -> None:
    thread = normalize_threads(
        [
            {
                "id": "thread-practical",
                "subject": "Tur på fredag",
                "latestMessageText": "Husk idrætstøj og medbring madpakke.",
            }
        ]
    )[0]

    assessment = assess_thread(thread, [])

    assert assessment.level is ImportanceLevel.MEDIUM
    assert {signal.signal for signal in assessment.signals} >= {"practical_logistics"}


def test_assess_thread_flags_general_optional_opportunities() -> None:
    thread = normalize_threads(
        [
            {
                "id": "thread-opportunity",
                "subject": "Fritidstilbud",
                "latestMessageText": "Der er gratis workshop og kursus efter skole.",
            }
        ]
    )[0]

    assessment = assess_thread(thread, [])

    assert assessment.level is ImportanceLevel.LOW
    assert {signal.signal for signal in assessment.signals} >= {"optional_opportunity"}
