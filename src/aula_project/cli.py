from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from aula_project.client import AulaDataClient
from aula_project.config import DEFAULT_ENV_FILE, load_settings
from aula_project.notifications import AppriseNotifier, build_notification_plan, send_notification
from aula_project.scan_state import load_scan_state, save_scan_state
from aula_project.scheduled_review import mark_reviewed


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aula-project")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--save-raw", action="store_true", help="Persist raw Aula payloads to disk.")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity: -v for WARNING, -vv for INFO, -vvv for DEBUG.",
    )
    parser.add_argument(
        "--auth-method",
        choices=("app", "token"),
        default=None,
        help="Override MitID authentication method for this run.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help="Overall timeout for Aula network commands. Use 0 to disable.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    profile_parser = subparsers.add_parser("profile", help="Print current Aula profile context as JSON.")
    profile_parser.set_defaults(command="profile")

    login_parser = subparsers.add_parser("login", help="Authenticate and initialize the Aula session.")
    login_parser.set_defaults(command="login")

    auth_status_parser = subparsers.add_parser(
        "auth-status",
        help="Inspect the local Aula token cache without contacting Aula.",
    )
    auth_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Print compact JSON status instead of text.",
    )
    auth_status_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include sanitized token and cookie diagnostics as JSON.",
    )
    auth_status_parser.set_defaults(command="auth-status")

    threads_parser = subparsers.add_parser("threads", help="List recent message threads as JSON.")
    threads_parser.add_argument("--limit", type=int, default=None)
    threads_parser.set_defaults(command="threads")

    messages_parser = subparsers.add_parser("messages", help="Fetch full messages for one thread as JSON.")
    messages_parser.add_argument("thread_id")
    messages_parser.set_defaults(command="messages")

    important_parser = subparsers.add_parser(
        "important",
        help="Rank likely-important message threads using deterministic rules.",
    )
    important_parser.add_argument("--thread-limit", type=int, default=None)
    important_parser.add_argument("--limit", type=int, default=None)
    important_parser.add_argument("--include-low", action="store_true")
    important_parser.set_defaults(command="important")

    review_new_parser = subparsers.add_parser(
        "review-new",
        help="Review messages received since the previous scheduled run.",
    )
    review_new_parser.add_argument("--thread-limit", type=int, default=None)
    review_new_parser.add_argument(
        "--since",
        default=None,
        help="Review messages after this ISO timestamp, ignoring the saved checkpoint for selection.",
    )
    review_new_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect new messages without calling OpenAI or updating scan state.",
    )
    review_new_parser.add_argument(
        "--no-openai",
        action="store_true",
        help="Collect new messages and update scan state without calling OpenAI.",
    )
    review_new_parser.add_argument(
        "--no-update-state",
        action="store_true",
        help="Do not write the scan checkpoint after a successful run.",
    )
    review_new_parser.add_argument(
        "--include-messages",
        action="store_true",
        help="Deprecated alias for --format json-verbose.",
    )
    review_new_parser.add_argument(
        "--format",
        choices=("json", "json-verbose", "text"),
        default="json",
        help="Output format: compact JSON, verbose JSON with normalized messages, or plain summary text.",
    )
    review_new_parser.add_argument(
        "--timeout-seconds",
        dest="command_timeout_seconds",
        type=float,
        default=None,
        help="Overall timeout for this review run. Use 0 to disable.",
    )
    review_new_parser.set_defaults(command="review-new")

    notify_new_parser = subparsers.add_parser(
        "notify-new",
        help="Review new Aula messages and send a notification when something is actionable.",
    )
    notify_new_parser.add_argument("--thread-limit", type=int, default=None)
    notify_new_parser.add_argument(
        "--since",
        default=None,
        help="Review messages after this ISO timestamp, ignoring the saved checkpoint for selection.",
    )
    notify_new_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Review and show the notification plan without sending or updating scan state.",
    )
    notify_new_parser.add_argument(
        "--no-openai",
        action="store_true",
        help="Use deterministic triage only.",
    )
    notify_new_parser.add_argument(
        "--no-update-state",
        action="store_true",
        help="Do not write the scan checkpoint after a successful run.",
    )
    notify_new_parser.add_argument(
        "--notify-url",
        default=None,
        help="Override AULA_NOTIFY_URL/AULA_NOTIFY_URLS for this run.",
    )
    notify_new_parser.add_argument(
        "--min-priority",
        choices=("low", "medium", "high"),
        default=None,
        help="Minimum priority required to send a notification.",
    )
    notify_new_parser.add_argument(
        "--timeout-seconds",
        dest="command_timeout_seconds",
        type=float,
        default=None,
        help="Overall timeout for this notification run. Use 0 to disable.",
    )
    notify_new_parser.set_defaults(command="notify-new")

    return parser


def _render(payload: Any, *, indent: int) -> None:
    print(json.dumps(payload, indent=indent, ensure_ascii=False, default=_json_default))


def _configure_logging(verbosity: int) -> None:
    level = logging.ERROR
    if verbosity == 1:
        level = logging.WARNING
    elif verbosity == 2:
        level = logging.INFO
    elif verbosity >= 3:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        force=True,
    )

    if level < logging.WARNING:
        for logger_name in ("httpx", "httpcore", "asyncio"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)


class _NoopNotifier:
    def notify(self, *, title: str, body: str) -> bool:
        return False


def _auth_status_summary(status: Any) -> dict[str, Any]:
    if not status.cache_exists:
        return {
            "status": "login_required",
            "logged_in": False,
            "message": "No Aula login cache was found. Run: uv run aula-project login",
        }

    if status.access_token_reusable:
        seconds = status.access_token_valid_for_seconds
        return {
            "status": "logged_in",
            "logged_in": True,
            "message": f"You are logged in. Cached access token is reusable for {_format_duration(seconds)}.",
            "access_token_expires_at": status.access_token_expires_at,
            "access_token_expires_at_local": status.access_token_expires_at_local,
            "local_timezone": status.local_timezone,
        }

    if status.refresh_token_present:
        return {
            "status": "refresh_available",
            "logged_in": True,
            "message": "Access token is expired, but a refresh token is available. The next Aula command should refresh the login automatically.",
            "access_token_expires_at": status.access_token_expires_at,
            "access_token_expires_at_local": status.access_token_expires_at_local,
            "local_timezone": status.local_timezone,
        }

    return {
        "status": "login_required",
        "logged_in": False,
        "message": "Aula login cache exists, but no reusable token was found. Run: uv run aula-project login",
        "access_token_expires_at": status.access_token_expires_at,
        "access_token_expires_at_local": status.access_token_expires_at_local,
        "local_timezone": status.local_timezone,
    }


def _format_auth_status_text(status: Any) -> str:
    summary = _auth_status_summary(status)
    lines = [summary["message"]]
    expires_at = _format_expiry_for_text(status)
    if expires_at:
        lines.append(f"Access token expires at: {expires_at}")
    lines.append(f"Cache path: {status.cache_path}")
    return "\n".join(lines)


def _format_expiry_for_text(status: Any) -> str | None:
    if status.access_token_expires_at_local:
        timezone = f" {status.local_timezone}" if status.local_timezone else ""
        return f"{status.access_token_expires_at_local}{timezone}"
    return status.access_token_expires_at


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "an unknown amount of time"
    if seconds < 0:
        return "0 minutes"
    minutes = seconds // 60
    if minutes < 1:
        return f"{seconds} seconds"
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        if remaining_minutes:
            return f"{hours}h {remaining_minutes}m"
        return f"{hours}h"
    return f"{minutes}m"


async def _with_timeout(awaitable: Any, *, timeout_seconds: float, operation: str) -> Any:
    if timeout_seconds <= 0:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise TimeoutError(f"{operation} timed out after {timeout_seconds:g} seconds.") from exc


async def _run_async(args: argparse.Namespace) -> int:
    _configure_logging(args.verbose)
    settings = load_settings(args.env_file, require_username=args.command != "auth-status")
    if args.auth_method is not None:
        settings.auth_method = args.auth_method
    timeout_override = getattr(args, "command_timeout_seconds", None)
    if timeout_override is None:
        timeout_override = args.timeout_seconds
    if timeout_override is not None:
        settings.request_timeout_seconds = timeout_override
    client = AulaDataClient(settings)

    if args.command == "login":
        profile, auth_result = await client.login(save_raw=args.save_raw)
        payload = {
            "status": "ok",
            "auth": auth_result.to_dict(),
            "profile_id": profile.profile_id,
            "display_name": profile.display_name,
        }
        _render(payload, indent=settings.json_indent)
        return 0

    if args.command == "auth-status":
        status = client.get_auth_cache_status()
        if args.verbose:
            _render(status.to_dict(), indent=settings.json_indent)
        elif args.json:
            _render(_auth_status_summary(status), indent=settings.json_indent)
        else:
            print(_format_auth_status_text(status))
        return 0

    if args.command == "profile":
        profile = await _with_timeout(
            client.get_profile(save_raw=args.save_raw),
            timeout_seconds=settings.request_timeout_seconds,
            operation="Fetching Aula profile",
        )
        _render(profile.to_dict(), indent=settings.json_indent)
        return 0

    if args.command == "threads":
        limit = args.limit if args.limit is not None else settings.default_limit
        threads = await _with_timeout(
            client.list_threads(limit=limit, save_raw=args.save_raw),
            timeout_seconds=settings.request_timeout_seconds,
            operation="Fetching Aula threads",
        )
        _render([thread.to_dict() for thread in threads], indent=settings.json_indent)
        return 0

    if args.command == "messages":
        messages = await _with_timeout(
            client.get_messages(args.thread_id, save_raw=args.save_raw),
            timeout_seconds=settings.request_timeout_seconds,
            operation=f"Fetching Aula messages for thread {args.thread_id}",
        )
        payload = {
            "thread_id": args.thread_id,
            "messages": [message.to_dict() for message in messages],
        }
        _render(payload, indent=settings.json_indent)
        return 0

    if args.command == "important":
        thread_limit = args.thread_limit if args.thread_limit is not None else settings.default_limit
        assessments = await _with_timeout(
            client.list_important_threads(
                thread_limit=thread_limit,
                result_limit=args.limit,
                include_low=args.include_low,
                save_raw=args.save_raw,
            ),
            timeout_seconds=settings.request_timeout_seconds,
            operation="Fetching and ranking Aula threads",
        )
        payload = {
            "thread_limit": thread_limit,
            "items": [assessment.to_dict() for assessment in assessments],
        }
        _render(payload, indent=settings.json_indent)
        return 0

    if args.command == "review-new":
        thread_limit = args.thread_limit if args.thread_limit is not None else settings.default_limit
        output_format = "json-verbose" if args.include_messages else args.format
        result = await _with_timeout(
            client.review_new_messages(
                thread_limit=thread_limit,
                since=args.since,
                call_openai=not args.dry_run and not args.no_openai,
                update_state=not args.dry_run and not args.no_update_state,
                save_raw=args.save_raw,
            ),
            timeout_seconds=settings.request_timeout_seconds,
            operation="Reviewing new Aula messages",
        )
        if output_format == "text":
            print(result.to_text())
            return 0

        payload = result.to_dict(include_messages=output_format == "json-verbose")
        payload["thread_limit"] = thread_limit
        payload["openai_model"] = settings.openai_model
        _render(payload, indent=settings.json_indent)
        return 0

    if args.command == "notify-new":
        thread_limit = args.thread_limit if args.thread_limit is not None else settings.default_limit
        result = await _with_timeout(
            client.review_new_messages(
                thread_limit=thread_limit,
                since=args.since,
                call_openai=not args.dry_run and not args.no_openai,
                update_state=False,
                save_raw=args.save_raw,
            ),
            timeout_seconds=settings.request_timeout_seconds,
            operation="Reviewing new Aula messages for notification",
        )
        plan = build_notification_plan(
            result,
            min_priority=args.min_priority or settings.notify_min_priority,
        )

        notification_result = None
        if args.dry_run:
            notification_result = {
                "plan": plan.to_dict(),
                "attempted": False,
                "sent": False,
                "error": None,
            }
        else:
            notify_urls = [args.notify_url.strip()] if args.notify_url and args.notify_url.strip() else settings.notify_urls
            if plan.should_notify:
                if notify_urls:
                    notification_result = send_notification(plan, AppriseNotifier(notify_urls)).to_dict()
                else:
                    notification_result = {
                        "plan": plan.to_dict(),
                        "attempted": False,
                        "sent": False,
                        "error": "Missing notification URL. Set AULA_NOTIFY_URL or AULA_NOTIFY_URLS.",
                    }
            else:
                notification_result = send_notification(plan, _NoopNotifier()).to_dict()

            notification_sent_or_unneeded = not plan.should_notify or bool(notification_result["sent"])
            if not args.no_update_state and notification_sent_or_unneeded:
                state = load_scan_state(settings.scan_state_path)
                next_state = mark_reviewed(state, result.items, checked_at=result.checked_at)
                save_scan_state(settings.scan_state_path, next_state)
                result.state_updated = True

        payload = result.to_dict(include_messages=False)
        payload["thread_limit"] = thread_limit
        payload["openai_model"] = settings.openai_model
        payload["notification"] = notification_result
        _render(payload, indent=settings.json_indent)
        notification_failed = bool(notification_result["error"]) or (
            notification_result["attempted"] and not notification_result["sent"]
        )
        return 2 if notification_failed else 0

    raise RuntimeError(f"Unknown command: {args.command}")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_run_async(args)))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130) from None
    except TimeoutError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
