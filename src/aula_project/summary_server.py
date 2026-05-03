from __future__ import annotations

import asyncio
from html import escape
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from aula_project.client import AulaDataClient
from aula_project.config import Settings


def build_summary_html(payload: dict[str, Any]) -> str:
    auth = payload["auth"]
    profile = payload.get("profile")
    important = payload.get("important_threads", [])
    status = escape(str(auth.get("message", "Unknown auth status")))
    profile_name = escape(str(profile.get("display_name") or profile.get("profile_id"))) if profile else "Unavailable"
    rows = "\n".join(_important_row(item) for item in important)
    if not rows:
        rows = '<tr><td colspan="4">No important Aula threads found.</td></tr>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="300">
  <title>Aula Summary</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; color: #1f2933; }}
    main {{ max-width: 980px; margin: 0 auto; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 0.25rem; }}
    .meta {{ color: #52606d; margin-bottom: 1.5rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #d9e2ec; padding: 0.65rem; text-align: left; vertical-align: top; }}
    th {{ color: #334e68; font-size: 0.85rem; text-transform: uppercase; }}
    .level-high {{ color: #b42318; font-weight: 700; }}
    .level-medium {{ color: #9a6700; font-weight: 700; }}
    .level-low {{ color: #3f6212; font-weight: 700; }}
  </style>
</head>
<body>
  <main>
    <h1>Aula Summary</h1>
    <div class="meta">{status}<br>Profile: {profile_name}<br>Checked: {escape(str(payload["checked_at"]))}</div>
    <table>
      <thead><tr><th>Priority</th><th>Thread</th><th>Score</th><th>Signals</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </main>
</body>
</html>
"""


async def build_summary_payload(
    settings: Settings,
    *,
    thread_limit: int | None,
    result_limit: int | None,
) -> dict[str, Any]:
    client = AulaDataClient(settings)
    auth = client.get_auth_cache_status()
    profile = await client.get_profile()
    important = await client.list_important_threads(
        thread_limit=thread_limit,
        result_limit=result_limit,
        include_low=False,
    )
    return {
        "checked_at": _utc_now_iso(),
        "auth": _auth_summary(auth),
        "profile": profile.to_dict(),
        "important_threads": [item.to_dict() for item in important],
    }


def run_summary_server(
    settings: Settings,
    *,
    host: str,
    port: int,
    thread_limit: int | None,
    result_limit: int | None,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path not in {"/", "/api/summary"}:
                self.send_error(404)
                return
            try:
                payload = asyncio.run(
                    build_summary_payload(
                        settings,
                        thread_limit=thread_limit,
                        result_limit=result_limit,
                    )
                )
                if path == "/api/summary":
                    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                else:
                    body = build_summary_html(payload).encode("utf-8")
                    content_type = "text/html; charset=utf-8"
            except Exception as exc:  # pragma: no cover - runtime diagnostics
                self.send_error(500, explain=str(exc))
                return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _important_row(item: dict[str, Any]) -> str:
    thread = item["thread"]
    level = str(item["level"])
    signals = ", ".join(signal["signal"].replace("_", " ") for signal in item.get("signals", [])[:4])
    return (
        "<tr>"
        f'<td class="level-{escape(level)}">{escape(level.title())}</td>'
        f"<td>{escape(str(thread.get('title') or '(no subject)'))}<br><small>{escape(str(thread.get('thread_id')))}</small></td>"
        f"<td>{escape(str(item.get('score', 0)))}</td>"
        f"<td>{escape(signals)}</td>"
        "</tr>"
    )


def _auth_summary(status: Any) -> dict[str, Any]:
    if status.access_token_reusable:
        message = "Cached Aula token is reusable."
    elif status.refresh_token_present:
        message = "Cached Aula token will refresh on the next Aula request."
    elif status.cache_exists:
        message = "Aula token cache exists, but login is required."
    else:
        message = "Aula login cache is missing."
    return {
        "message": message,
        "cache_exists": status.cache_exists,
        "access_token_reusable": status.access_token_reusable,
        "access_token_expires_at_local": status.access_token_expires_at_local,
        "refresh_token_present": status.refresh_token_present,
    }


def _utc_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
