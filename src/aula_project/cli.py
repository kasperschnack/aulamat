from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from aula_project.client import AulaDataClient
from aula_project.config import DEFAULT_ENV_FILE, load_settings


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

    subparsers = parser.add_subparsers(dest="command", required=True)

    profile_parser = subparsers.add_parser("profile", help="Print current Aula profile context as JSON.")
    profile_parser.set_defaults(command="profile")

    login_parser = subparsers.add_parser("login", help="Authenticate and initialize the Aula session.")
    login_parser.set_defaults(command="login")

    auth_status_parser = subparsers.add_parser(
        "auth-status",
        help="Inspect the local Aula token cache without contacting Aula.",
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


async def _run_async(args: argparse.Namespace) -> int:
    _configure_logging(args.verbose)
    settings = load_settings(args.env_file, require_username=args.command != "auth-status")
    if args.auth_method is not None:
        settings.auth_method = args.auth_method
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
        _render(client.get_auth_cache_status().to_dict(), indent=settings.json_indent)
        return 0

    if args.command == "profile":
        profile = await client.get_profile(save_raw=args.save_raw)
        _render(profile.to_dict(), indent=settings.json_indent)
        return 0

    if args.command == "threads":
        limit = args.limit if args.limit is not None else settings.default_limit
        threads = await client.list_threads(limit=limit, save_raw=args.save_raw)
        _render([thread.to_dict() for thread in threads], indent=settings.json_indent)
        return 0

    if args.command == "messages":
        messages = await client.get_messages(args.thread_id, save_raw=args.save_raw)
        payload = {
            "thread_id": args.thread_id,
            "messages": [message.to_dict() for message in messages],
        }
        _render(payload, indent=settings.json_indent)
        return 0

    if args.command == "important":
        thread_limit = args.thread_limit if args.thread_limit is not None else settings.default_limit
        assessments = await client.list_important_threads(
            thread_limit=thread_limit,
            result_limit=args.limit,
            include_low=args.include_low,
            save_raw=args.save_raw,
        )
        payload = {
            "thread_limit": thread_limit,
            "items": [assessment.to_dict() for assessment in assessments],
        }
        _render(payload, indent=settings.json_indent)
        return 0

    raise RuntimeError(f"Unknown command: {args.command}")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run_async(args)))


if __name__ == "__main__":
    main()
