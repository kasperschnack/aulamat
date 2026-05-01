from __future__ import annotations

import pytest

from aula_project.cli import _auth_status_summary, _build_parser, _format_auth_status_text, _with_timeout
from aula_project.models import AuthCacheStatus


def test_review_and_notify_accept_command_timeout_option() -> None:
    parser = _build_parser()

    review_args = parser.parse_args(["review-new", "--timeout-seconds", "20"])
    notify_args = parser.parse_args(["notify-new", "--timeout-seconds", "15"])

    assert review_args.command_timeout_seconds == 20
    assert notify_args.command_timeout_seconds == 15


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
