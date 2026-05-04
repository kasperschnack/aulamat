from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
import subprocess
import sys
from typing import Any

from aula_project.client import AulaDataClient
from aula_project.config import DEFAULT_ENV_FILE, load_settings
from aula_project.models import (
    MessageItem,
    MessageThread,
    Profile,
    ThreadAssessment,
)
from aula_project.notifications import (
    AppriseNotifier,
    TerminalNotifier,
    build_notification_plan,
    send_notification,
)
from aula_project.scan_state import load_scan_state, save_scan_state
from aula_project.scheduled_review import mark_reviewed
from aula_project.service import (
    DEFAULT_SUMMARY_SERVER_PORT,
    build_launchd_service,
    build_summary_launchd_service,
    launchd_plist,
    write_launchd_plist,
)
from aula_project.summary_server import run_summary_server


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

    profile_parser = subparsers.add_parser("profile", help="Print current Aula profile context.")
    profile_parser.add_argument("--json", action="store_true", help="Print full normalized profile as JSON.")
    profile_parser.set_defaults(command="profile")

    login_parser = subparsers.add_parser("login", help="Authenticate and initialize the Aula session.")
    login_parser.add_argument("--json", action="store_true", help="Print login result as JSON.")
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

    threads_parser = subparsers.add_parser("threads", help="List recent message threads.")
    threads_parser.add_argument("--limit", type=int, default=None)
    threads_parser.add_argument("--json", action="store_true", help="Print normalized threads as JSON.")
    threads_parser.set_defaults(command="threads")

    messages_parser = subparsers.add_parser("messages", help="Fetch full messages for one thread.")
    messages_parser.add_argument("thread_id")
    messages_parser.add_argument("--json", action="store_true", help="Print normalized messages as JSON.")
    messages_parser.set_defaults(command="messages")

    important_parser = subparsers.add_parser(
        "important",
        help="Rank likely-important message threads using deterministic rules.",
    )
    important_parser.add_argument("--thread-limit", type=int, default=None)
    important_parser.add_argument("--limit", type=int, default=None)
    important_parser.add_argument("--include-low", action="store_true")
    important_parser.add_argument("--json", action="store_true", help="Print ranked threads as JSON.")
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
        default="text",
        help="Output format: compact JSON, verbose JSON with normalized messages, or plain summary text.",
    )
    review_new_parser.add_argument(
        "--json",
        action="store_true",
        help="Print compact JSON. Equivalent to --format json.",
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
    notify_new_parser.add_argument("--json", action="store_true", help="Print review and notification plan as JSON.")
    notify_new_parser.set_defaults(command="notify-new")

    install_service_parser = subparsers.add_parser(
        "install-service",
        help="Install a macOS launchd job that runs notify-new on an interval.",
    )
    install_service_parser.add_argument("--interval-minutes", type=int, default=20)
    install_service_parser.add_argument("--thread-limit", type=int, default=None)
    install_service_parser.add_argument("--min-priority", choices=("low", "medium", "high"), default=None)
    install_service_parser.add_argument("--no-openai", action="store_true")
    install_service_parser.add_argument("--label", default="dk.local.aula-project.notify")
    install_service_parser.add_argument("--plist-dir", default=None)
    install_service_parser.add_argument(
        "--no-summary-server",
        action="store_true",
        help="Only install the notification checker, not the always-on summary server.",
    )
    install_service_parser.add_argument("--summary-label", default="dk.local.aula-project.summary")
    install_service_parser.add_argument("--summary-host", default="127.0.0.1")
    install_service_parser.add_argument("--summary-port", type=int, default=DEFAULT_SUMMARY_SERVER_PORT)
    install_service_parser.add_argument("--summary-limit", type=int, default=10)
    install_service_parser.add_argument("--load", action="store_true", help="Load the launchd job after writing it.")
    install_service_parser.add_argument("--json", action="store_true", help="Print installed service details as JSON.")
    install_service_parser.set_defaults(command="install-service")

    summary_server_parser = subparsers.add_parser(
        "summary-server",
        help="Serve a local Aula summary page and JSON endpoint.",
    )
    summary_server_parser.add_argument("--host", default="127.0.0.1")
    summary_server_parser.add_argument("--port", type=int, default=DEFAULT_SUMMARY_SERVER_PORT)
    summary_server_parser.add_argument("--thread-limit", type=int, default=None)
    summary_server_parser.add_argument("--limit", type=int, default=10)
    summary_server_parser.set_defaults(command="summary-server")

    return parser


def _render(payload: Any, *, indent: int) -> None:
    print(json.dumps(payload, indent=indent, ensure_ascii=False, default=_json_default))


def _single_line(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def _format_profile_text(profile: Profile) -> str:
    name = profile.display_name or "(unknown name)"
    lines = [f"Logged in as {name}", f"Profile ID: {profile.profile_id}"]
    if profile.role:
        lines.append(f"Role: {profile.role}")
    if profile.children:
        lines.append("Children:")
        for child in profile.children:
            child_name = child.display_name or child.child_id
            institution = f" ({child.institution_name})" if child.institution_name else ""
            lines.append(f"- {child_name}{institution}")
    return "\n".join(lines)


def _format_threads_text(threads: list[MessageThread]) -> str:
    if not threads:
        return "No Aula threads found."

    lines = [f"Aula threads ({len(threads)}):"]
    for thread in threads:
        title = _truncate(_single_line(thread.title) or "(no subject)", 80)
        unread = " unread" if thread.unread else ""
        lines.append(f"- {title}{unread}")
        details = [f"ID: {thread.thread_id}"]
        if thread.last_message_at:
            details.append(f"Last: {thread.last_message_at}")
        if thread.participants:
            details.append("Participants: " + ", ".join(thread.participants[:3]))
        if thread.preview_text:
            details.append("Preview: " + _truncate(_single_line(thread.preview_text), 90))
        lines.append(f"  {' | '.join(details)}")
    return "\n".join(lines)


def _format_messages_text(thread_id: str, messages: list[MessageItem]) -> str:
    if not messages:
        return f"No Aula messages found for thread {thread_id}."

    lines = [f"Aula messages in thread {thread_id} ({len(messages)}):"]
    for message in messages:
        sender = message.sender_name or "Unknown sender"
        sent_at = f" | {message.sent_at}" if message.sent_at else ""
        lines.append(f"- {sender}{sent_at}")
        preview = _single_line(message.body_text)
        if preview:
            lines.append(f"  {_truncate(preview, 140)}")
        if message.attachments:
            filenames = [
                attachment.filename or attachment.attachment_id
                for attachment in message.attachments[:3]
            ]
            extra = f" (+{len(message.attachments) - 3} more)" if len(message.attachments) > 3 else ""
            lines.append(f"  Attachments: {', '.join(filenames)}{extra}")
    return "\n".join(lines)


def _format_important_text(assessments: list[ThreadAssessment]) -> str:
    if not assessments:
        return "No important Aula threads found."

    lines = [f"Important Aula threads ({len(assessments)}):"]
    for assessment in assessments:
        thread = assessment.thread
        level = assessment.level.value
        title = _truncate(_single_line(thread.title) or "(no subject)", 80)
        lines.append(f"- {level.capitalize()}: {title}")
        details = [f"ID: {thread.thread_id}", f"Score: {assessment.score}"]
        if assessment.signals:
            details.append(
                "Signals: "
                + ", ".join(signal.signal.replace("_", " ") for signal in assessment.signals[:4])
            )
        lines.append(f"  {' | '.join(details)}")
    return "\n".join(lines)


def _format_notify_text(payload: dict[str, Any]) -> str:
    notification = payload["notification"]
    plan = notification["plan"]
    if not plan["should_notify"]:
        return "No notification needed."

    title = plan["title"]
    body = plan["body"]
    if notification["sent"]:
        status = "Notification sent."
    elif notification["attempted"]:
        status = "Notification failed."
    else:
        status = "Notification not sent."

    lines = [status, title]
    if body:
        lines.append(body)
    if notification["error"]:
        lines.append(f"Error: {notification['error']}")
    return "\n".join(lines)


def _notification_backend_text(notify_urls: list[str]) -> str:
    if notify_urls:
        return "Apprise"
    if TerminalNotifier.available():
        return "terminal-notifier"
    return "none"


def _build_notifier(notify_urls: list[str]) -> Any:
    if notify_urls:
        return AppriseNotifier(notify_urls)
    return TerminalNotifier()


def _format_service_text(payload: dict[str, Any]) -> str:
    services = payload.get("services", [payload])
    lines = ["Installed Aula services:"]
    for service in services:
        lines.append(f"- {service['label']}")
        lines.append(f"  Plist: {service['plist_path']}")
        interval_minutes = service.get("interval_minutes")
        if interval_minutes is None:
            lines.append("  Mode: always on")
        else:
            lines.append(f"  Interval: {interval_minutes}m")
        lines.append("  Command: " + " ".join(service["command"]))
        if service.get("loaded"):
            lines.append("  Launchd job loaded.")
        elif service.get("load_error"):
            lines.append(f"  Launchd load failed: {service['load_error']}")
    summary_url = payload.get("summary_url")
    if summary_url:
        lines.append(f"Summary: {summary_url}")
    return "\n".join(lines)


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
            "message": "Access token is expired or expiring soon, but a refresh token is available. The next Aula command should refresh the login automatically.",
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
    settings = load_settings(args.env_file, require_username=args.command not in {"auth-status", "install-service"})
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
        if args.json or args.verbose:
            _render(payload, indent=settings.json_indent)
        else:
            print(_format_profile_text(profile))
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
        if args.json or args.verbose:
            _render(profile.to_dict(), indent=settings.json_indent)
        else:
            print(_format_profile_text(profile))
        return 0

    if args.command == "threads":
        limit = args.limit if args.limit is not None else settings.default_limit
        threads = await _with_timeout(
            client.list_threads(limit=limit, save_raw=args.save_raw),
            timeout_seconds=settings.request_timeout_seconds,
            operation="Fetching Aula threads",
        )
        if args.json or args.verbose:
            _render([thread.to_dict() for thread in threads], indent=settings.json_indent)
        else:
            print(_format_threads_text(threads))
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
        if args.json or args.verbose:
            _render(payload, indent=settings.json_indent)
        else:
            print(_format_messages_text(args.thread_id, messages))
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
        if args.json or args.verbose:
            _render(payload, indent=settings.json_indent)
        else:
            print(_format_important_text(assessments))
        return 0

    if args.command == "review-new":
        thread_limit = args.thread_limit if args.thread_limit is not None else settings.default_limit
        output_format = "json" if args.json else args.format
        if args.include_messages:
            output_format = "json-verbose"
        if args.verbose and output_format == "text":
            output_format = "json-verbose"
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
                    notification_result = send_notification(plan, _build_notifier(notify_urls)).to_dict()
                elif TerminalNotifier.available():
                    notification_result = send_notification(plan, _build_notifier([])).to_dict()
                else:
                    notification_result = {
                        "plan": plan.to_dict(),
                        "attempted": False,
                        "sent": False,
                        "error": "No notifier is available. Install terminal-notifier or set AULA_NOTIFY_URL/AULA_NOTIFY_URLS.",
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
        payload["notification_backend"] = _notification_backend_text(
            [args.notify_url.strip()] if args.notify_url and args.notify_url.strip() else settings.notify_urls
        )
        payload["notification"] = notification_result
        if args.json or args.verbose:
            _render(payload, indent=settings.json_indent)
        else:
            print(_format_notify_text(payload))
        notification_failed = bool(notification_result["error"]) or (
            notification_result["attempted"] and not notification_result["sent"]
        )
        return 2 if notification_failed else 0

    if args.command == "install-service":
        plist_dir = Path(args.plist_dir).expanduser() if args.plist_dir else None
        notification_service = build_launchd_service(
            project_dir=Path.cwd(),
            interval_minutes=args.interval_minutes,
            thread_limit=args.thread_limit,
            min_priority=args.min_priority,
            no_openai=args.no_openai,
            label=args.label,
            plist_dir=plist_dir,
        )
        services = [notification_service]
        if not args.no_summary_server:
            services.append(
                build_summary_launchd_service(
                    project_dir=Path.cwd(),
                    host=args.summary_host,
                    port=args.summary_port,
                    thread_limit=args.thread_limit,
                    result_limit=args.summary_limit,
                    label=args.summary_label,
                    plist_dir=plist_dir,
                )
            )

        service_payloads = []
        for service in services:
            write_launchd_plist(service, project_dir=Path.cwd())
            service_payload = service.to_dict()
            service_payload["plist"] = launchd_plist(service, project_dir=Path.cwd())
            service_payload["loaded"] = False
            service_payload["load_error"] = None
            if args.load:
                load_result = _load_launchd_service(service.plist_path)
                service_payload["loaded"] = load_result["loaded"]
                service_payload["load_error"] = load_result["load_error"]
            service_payloads.append(service_payload)

        payload = {
            "services": service_payloads,
            "summary_url": None
            if args.no_summary_server
            else f"http://{args.summary_host}:{args.summary_port}/",
        }
        load_failed = any(service.get("load_error") for service in service_payloads)
        if args.json or args.verbose:
            _render(payload, indent=settings.json_indent)
        else:
            print(_format_service_text(payload))
        return 2 if load_failed else 0

    if args.command == "summary-server":
        thread_limit = args.thread_limit if args.thread_limit is not None else settings.default_limit
        print(f"Serving Aula summary on http://{args.host}:{args.port}")
        run_summary_server(
            settings,
            host=args.host,
            port=args.port,
            thread_limit=thread_limit,
            result_limit=args.limit,
        )
        return 0

    raise RuntimeError(f"Unknown command: {args.command}")


def _load_launchd_service(plist_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return {"loaded": True, "load_error": None}

    message = result.stderr.strip() or result.stdout.strip() or None
    if message and "service already loaded" in message.lower():
        return {"loaded": True, "load_error": None}
    return {"loaded": False, "load_error": message}


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
