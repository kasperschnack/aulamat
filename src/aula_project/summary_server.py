from __future__ import annotations

import asyncio
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from aula_project.client import AulaDataClient
from aula_project.config import Settings


def build_summary_shell_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aula Summary</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; color: #1f2933; }
    main { max-width: 980px; margin: 0 auto; }
    h1 { font-size: 1.8rem; margin-bottom: 0.25rem; }
    .meta { color: #52606d; margin-bottom: 1.5rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid #d9e2ec; padding: 0.65rem; text-align: left; vertical-align: top; }
    th { color: #334e68; font-size: 0.85rem; text-transform: uppercase; }
    .thread-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
    .thread-title { font-weight: 700; }
    .thread-time { color: #52606d; font-size: 0.85rem; white-space: nowrap; }
    .message { margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid #edf2f7; }
    .message-meta { color: #52606d; font-size: 0.85rem; margin-bottom: 0.25rem; }
    .message-preview { line-height: 1.45; }
    .message-full-text { margin-top: 0.4rem; }
    .message-full-text summary { display: inline-block; cursor: pointer; border: 1px solid #bcccdc; border-radius: 6px; padding: 0.25rem 0.55rem; color: #243b53; font-size: 0.85rem; }
    .message-full-text summary:hover { background: #f0f4f8; }
    .message-body { margin-top: 0.45rem; white-space: pre-wrap; line-height: 1.45; }
    .attachments { color: #52606d; font-size: 0.85rem; margin-top: 0.35rem; }
    .level-high { color: #b42318; font-weight: 700; }
    .level-medium { color: #9a6700; font-weight: 700; }
    .level-low { color: #3f6212; font-weight: 700; }
  </style>
</head>
<body>
  <main>
    <h1>Aula Summary</h1>
    <div class="meta" id="meta">Loading Aula summary...</div>
    <table>
      <thead><tr><th>Priority</th><th>Thread and messages</th><th>Score</th><th>Signals</th></tr></thead>
      <tbody id="rows"><tr><td colspan="4">Loading...</td></tr></tbody>
    </table>
  </main>
  <script>
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));

    const truncate = (value, limit) => {
      const text = String(value ?? "");
      return text.length <= limit ? text : `${text.slice(0, limit - 1).trimEnd()}...`;
    };

    const formatDateTime = (value) => {
      if (!value) return "";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
    };

    const render = (payload) => {
      const profile = payload.profile || {};
      const profileName = profile.display_name || profile.profile_id || "Unavailable";
      const cache = payload.summary_cache || {};
      const cacheLine = cache.status === "stale"
        ? `<br>Showing cached summary from ${escapeHtml(cache.cached_at || payload.checked_at)} because live Aula refresh failed: ${escapeHtml(cache.error || "unknown error")}`
        : "";
      document.getElementById("meta").innerHTML = `${escapeHtml(payload.auth?.message || "Unknown auth status")}<br>Profile: ${escapeHtml(profileName)}<br>Checked: ${escapeHtml(payload.checked_at)}${cacheLine}`;

      const important = payload.important_threads || [];
      const rows = important.map((item) => {
        const thread = item.thread || {};
        const level = String(item.level || "low");
        const signals = (item.signals || []).slice(0, 4).map((signal) => String(signal.signal || "").replaceAll("_", " ")).join(", ");
        const itemMessages = item.messages || [];
        const threadTime = formatDateTime(thread.last_message_at || itemMessages.find((message) => message.sent_at)?.sent_at);
        const messages = itemMessages.map((message) => {
          const attachments = (message.attachments || []).map((attachment) => attachment.filename || attachment.attachment_id).filter(Boolean);
          const attachmentHtml = attachments.length ? `<div class="attachments">Attachments: ${escapeHtml(attachments.join(", "))}</div>` : "";
          const bodyText = message.body_text || "(no message text)";
          const preview = truncate(bodyText.replace(/\\s+/g, " ").trim(), 180);
          return `<div class="message"><div class="message-meta">${escapeHtml(message.sender_name || "Unknown sender")}${message.sent_at ? ` - ${escapeHtml(message.sent_at)}` : ""}</div><div class="message-preview">${escapeHtml(preview)}</div><details class="message-full-text"><summary>Full text</summary><div class="message-body">${escapeHtml(bodyText)}</div></details>${attachmentHtml}</div>`;
        }).join("");
        const timeHtml = threadTime ? `<span class="thread-time">${escapeHtml(threadTime)}</span>` : "";
        return `<tr><td class="level-${escapeHtml(level)}">${escapeHtml(level.charAt(0).toUpperCase() + level.slice(1))}</td><td><div class="thread-heading"><div class="thread-title">${escapeHtml(thread.title || "(no subject)")}</div>${timeHtml}</div><small>${escapeHtml(thread.thread_id)}</small>${messages}</td><td>${escapeHtml(item.score || 0)}</td><td>${escapeHtml(signals)}</td></tr>`;
      }).join("");
      document.getElementById("rows").innerHTML = rows || '<tr><td colspan="4">No important Aula threads found.</td></tr>';
    };

    const load = async () => {
      try {
        const response = await fetch("/api/summary", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        render(await response.json());
      } catch (error) {
        document.getElementById("meta").textContent = `Failed to load Aula summary: ${error.message}`;
        document.getElementById("rows").innerHTML = '<tr><td colspan="4">Summary data unavailable.</td></tr>';
      }
    };

    load();
    setInterval(load, 300000);
  </script>
</body>
</html>
"""


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
    .thread-heading {{ display: flex; align-items: baseline; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }}
    .thread-title {{ font-weight: 700; }}
    .thread-time {{ color: #52606d; font-size: 0.85rem; white-space: nowrap; }}
    .message {{ margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid #edf2f7; }}
    .message-meta {{ color: #52606d; font-size: 0.85rem; margin-bottom: 0.25rem; }}
    .message-preview {{ line-height: 1.45; }}
    .message-full-text {{ margin-top: 0.4rem; }}
    .message-full-text summary {{ display: inline-block; cursor: pointer; border: 1px solid #bcccdc; border-radius: 6px; padding: 0.25rem 0.55rem; color: #243b53; font-size: 0.85rem; }}
    .message-full-text summary:hover {{ background: #f0f4f8; }}
    .message-body {{ margin-top: 0.45rem; white-space: pre-wrap; line-height: 1.45; }}
    .attachments {{ color: #52606d; font-size: 0.85rem; margin-top: 0.35rem; }}
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
      <thead><tr><th>Priority</th><th>Thread and messages</th><th>Score</th><th>Signals</th></tr></thead>
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


class SummaryPayloadCache:
    def __init__(self, path: Path, *, ttl_seconds: float) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self._payload: dict[str, Any] | None = None
        self._loaded_at = 0.0

    async def get(
        self,
        settings: Settings,
        *,
        thread_limit: int | None,
        result_limit: int | None,
    ) -> dict[str, Any]:
        now = time.monotonic()
        if self._payload is not None and self.ttl_seconds > 0 and now - self._loaded_at <= self.ttl_seconds:
            return self._with_cache_status(self._payload, status="hit")

        try:
            payload = await build_summary_payload(
                settings,
                thread_limit=thread_limit,
                result_limit=result_limit,
            )
        except Exception as exc:
            stale = self._payload or self._load_persisted()
            if stale is None:
                raise
            return self._with_cache_status(stale, status="stale", error=str(exc))

        self._payload = payload
        self._loaded_at = now
        self._save_persisted(payload)
        return self._with_cache_status(payload, status="fresh")

    def _with_cache_status(
        self,
        payload: dict[str, Any],
        *,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        annotated = deepcopy(payload)
        cached_at = str(payload.get("checked_at") or "")
        annotated["summary_cache"] = {
            "status": status,
            "cached_at": cached_at,
            "ttl_seconds": self.ttl_seconds,
        }
        if error:
            annotated["summary_cache"]["error"] = error
        return annotated

    def _load_persisted(self) -> dict[str, Any] | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        self._payload = raw
        self._loaded_at = 0.0
        return raw

    def _save_persisted(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_summary_server(
    settings: Settings,
    *,
    host: str,
    port: int,
    thread_limit: int | None,
    result_limit: int | None,
) -> None:
    payload_cache = SummaryPayloadCache(
        settings.summary_cache_path,
        ttl_seconds=settings.summary_cache_seconds,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path not in {"/", "/api/summary"}:
                self.send_error(404)
                return
            try:
                if path == "/":
                    body = build_summary_shell_html().encode("utf-8")
                    content_type = "text/html; charset=utf-8"
                else:
                    payload = asyncio.run(
                        payload_cache.get(
                            settings,
                            thread_limit=thread_limit,
                            result_limit=result_limit,
                        )
                    )
                    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
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
    messages = "".join(_message_block(message) for message in item.get("messages", []))
    thread_time = _format_display_datetime(thread.get("last_message_at") or _first_message_sent_at(item))
    thread_time_html = f'<span class="thread-time">{escape(thread_time)}</span>' if thread_time else ""
    return (
        "<tr>"
        f'<td class="level-{escape(level)}">{escape(level.title())}</td>'
        f'<td><div class="thread-heading"><div class="thread-title">{escape(str(thread.get("title") or "(no subject)"))}</div>'
        f"{thread_time_html}</div>"
        f"<small>{escape(str(thread.get('thread_id')))}</small>{messages}</td>"
        f"<td>{escape(str(item.get('score', 0)))}</td>"
        f"<td>{escape(signals)}</td>"
        "</tr>"
    )


def _message_block(message: dict[str, Any]) -> str:
    sender = escape(str(message.get("sender_name") or "Unknown sender"))
    sent_at = message.get("sent_at")
    meta = sender if not sent_at else f"{sender} - {escape(str(sent_at))}"
    body_text = str(message.get("body_text") or "(no message text)")
    preview = escape(_truncate_single_line(body_text, 180))
    body = escape(body_text)
    attachments = [
        str(attachment.get("filename") or attachment.get("attachment_id"))
        for attachment in message.get("attachments", [])
        if attachment.get("filename") or attachment.get("attachment_id")
    ]
    attachment_html = ""
    if attachments:
        attachment_html = f'<div class="attachments">Attachments: {escape(", ".join(attachments))}</div>'
    return (
        '<div class="message">'
        f'<div class="message-meta">{meta}</div>'
        f'<div class="message-preview">{preview}</div>'
        f'<details class="message-full-text"><summary>Full text</summary><div class="message-body">{body}</div></details>'
        f"{attachment_html}"
        "</div>"
    )


def _first_message_sent_at(item: dict[str, Any]) -> Any:
    for message in item.get("messages", []):
        if isinstance(message, dict) and message.get("sent_at"):
            return message["sent_at"]
    return None


def _truncate_single_line(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _format_display_datetime(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        from datetime import datetime

        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    return parsed.strftime("%Y-%m-%d %H:%M")


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
