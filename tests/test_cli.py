from __future__ import annotations

import pytest

from aula_project.cli import (
    _auth_status_summary,
    _build_parser,
    _format_auth_status_text,
    _format_important_text,
    _format_messages_text,
    _format_service_text,
    _format_threads_text,
    _with_timeout,
)
from aula_project.models import (
    AuthCacheStatus,
    ImportanceLevel,
    MessageItem,
    MessageSource,
    MessageThread,
    ThreadAssessment,
)


def test_review_and_notify_accept_command_timeout_option() -> None:
    parser = _build_parser()

    review_args = parser.parse_args(["review-new", "--timeout-seconds", "20"])
    notify_args = parser.parse_args(["notify-new", "--timeout-seconds", "15"])

    assert review_args.command_timeout_seconds == 20
    assert notify_args.command_timeout_seconds == 15


def test_review_new_defaults_to_text_but_accepts_json_flag() -> None:
    parser = _build_parser()

    default_args = parser.parse_args(["review-new"])
    json_args = parser.parse_args(["review-new", "--json"])

    assert default_args.format == "text"
    assert json_args.json is True


def test_install_service_defaults_to_summary_server() -> None:
    parser = _build_parser()

    args = parser.parse_args(["install-service"])

    assert args.no_summary_server is False
    assert args.summary_host == "127.0.0.1"
    assert args.summary_port == 8767
    assert args.summary_limit == 10


def test_service_text_shows_multiple_services_and_summary_url() -> None:
    text = _format_service_text(
        {
            "summary_url": "http://127.0.0.1:8767/",
            "services": [
                {
                    "label": "dk.local.aula-project.notify",
                    "plist_path": "/tmp/notify.plist",
                    "interval_minutes": 20,
                    "command": ["uv", "run", "aula-project", "notify-new"],
                    "loaded": True,
                    "load_error": None,
                },
                {
                    "label": "dk.local.aula-project.summary",
                    "plist_path": "/tmp/summary.plist",
                    "interval_minutes": None,
                    "command": ["uv", "run", "aula-project", "summary-server"],
                    "loaded": True,
                    "load_error": None,
                },
            ],
        }
    )

    assert "dk.local.aula-project.notify" in text
    assert "Interval: 20m" in text
    assert "dk.local.aula-project.summary" in text
    assert "Mode: always on" in text
    assert "Summary: http://127.0.0.1:8767/" in text


def test_threads_text_is_clean_and_omits_raw_json() -> None:
    thread = MessageThread(
        thread_id="163184660",
        source=MessageSource.AULA,
        title="glemt liggeunderlags pose til\nfødselsdag",
        raw={"thread_id": 163184660, "subject": "glemt liggeunderlags pose til fødselsdag"},
    )

    text = _format_threads_text([thread])

    assert text == (
        "Aula threads (1):\n"
        "- glemt liggeunderlags pose til fødselsdag\n"
        "  ID: 163184660"
    )
    assert "raw" not in text
    assert "{" not in text


def test_messages_text_shows_sender_preview_and_attachments() -> None:
    message = MessageItem(
        message_id="msg-1",
        thread_id="thread-1",
        source=MessageSource.AULA,
        sender_name="Lærer Line",
        sent_at="2026-04-29T08:15:00Z",
        body_text="Husk idrætstøj og madpakke.",
    )

    text = _format_messages_text("thread-1", [message])

    assert text == (
        "Aula messages in thread thread-1 (1):\n"
        "- Lærer Line | 2026-04-29T08:15:00Z\n"
        "  Husk idrætstøj og madpakke."
    )


def test_important_text_summarizes_assessments() -> None:
    thread = MessageThread(thread_id="thread-1", source=MessageSource.AULA, title="Tur i morgen")
    assessment = ThreadAssessment(thread=thread, level=ImportanceLevel.MEDIUM, score=5)

    text = _format_important_text([assessment])

    assert text == (
        "Important Aula threads (1):\n"
        "- Medium: Tur i morgen\n"
        "  ID: thread-1 | Score: 5"
    )


def test_auth_status_summary_reports_logged_in_when_access_token_reusable() -> None:
    status = AuthCacheStatus(
        cache_path=".aula_tokens.json",
        cache_exists=True,
        access_token_expires_at="2026-05-01T07:25:30Z",
        access_token_expires_at_local="2026-05-01T09:25:30+02:00",
        local_timezone="CEST",
        access_token_valid_for_seconds=3357,
        access_token_reusable=True,
        refresh_token_present=True,
    )

    summary = _auth_status_summary(status)

    assert summary["status"] == "logged_in"
    assert summary["logged_in"] is True
    assert "reusable for 55m" in summary["message"]
    assert summary["access_token_expires_at_local"] == "2026-05-01T09:25:30+02:00"
    assert summary["local_timezone"] == "CEST"


def test_auth_status_text_shows_only_local_expiry() -> None:
    status = AuthCacheStatus(
        cache_path=".aula_tokens.json",
        cache_exists=True,
        access_token_expires_at="2026-05-01T07:25:30Z",
        access_token_expires_at_local="2026-05-01T09:25:30+02:00",
        local_timezone="CEST",
        access_token_valid_for_seconds=3357,
        access_token_reusable=True,
        refresh_token_present=True,
    )

    text = _format_auth_status_text(status)

    assert text == (
        "You are logged in. Cached access token is reusable for 55m.\n"
        "Access token expires at: 2026-05-01T09:25:30+02:00 CEST\n"
        "Cache path: .aula_tokens.json"
    )
    assert "UTC" not in text
    assert "2026-05-01T07:25:30Z" not in text


def test_auth_status_json_summary_keeps_local_and_utc_expiry() -> None:
    status = AuthCacheStatus(
        cache_path=".aula_tokens.json",
        cache_exists=True,
        access_token_expires_at="2026-05-01T07:25:30Z",
        access_token_expires_at_local="2026-05-01T09:25:30+02:00",
        local_timezone="CEST",
        access_token_valid_for_seconds=3357,
        access_token_reusable=True,
        refresh_token_present=True,
    )

    summary = _auth_status_summary(status)

    assert summary["access_token_expires_at"] == "2026-05-01T07:25:30Z"
    assert summary["access_token_expires_at_local"] == "2026-05-01T09:25:30+02:00"


def test_auth_status_summary_reports_refresh_available_for_expired_access_token() -> None:
    status = AuthCacheStatus(
        cache_path=".aula_tokens.json",
        cache_exists=True,
        access_token_reusable=False,
        refresh_token_present=True,
    )

    summary = _auth_status_summary(status)

    assert summary["status"] == "refresh_available"
    assert summary["logged_in"] is True
    assert "refresh token is available" in summary["message"]
    assert "expired or expiring soon" in summary["message"]


def test_auth_status_text_reports_login_required_without_cache() -> None:
    status = AuthCacheStatus(cache_path=".aula_tokens.json", cache_exists=False)

    text = _format_auth_status_text(status)

    assert text == (
        "No Aula login cache was found. Run: uv run aula-project login\n"
        "Cache path: .aula_tokens.json"
    )


@pytest.mark.anyio
async def test_with_timeout_reports_operation_name() -> None:
    async def slow() -> None:
        import asyncio

        await asyncio.sleep(1)

    with pytest.raises(TimeoutError, match="Testing timeout timed out after 0.001 seconds"):
        await _with_timeout(slow(), timeout_seconds=0.001, operation="Testing timeout")
