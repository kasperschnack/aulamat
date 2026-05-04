from __future__ import annotations

from pathlib import Path
import plistlib

from aula_project.service import build_launchd_service, build_summary_launchd_service, launchd_plist, write_launchd_plist
from aula_project.summary_server import SummaryPayloadCache, build_summary_html


def test_build_launchd_service_plist_contains_notify_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aula_project.service.shutil.which", lambda name: "/opt/homebrew/bin/uv")
    project_dir = tmp_path / "project"
    plist_dir = tmp_path / "LaunchAgents"

    service = build_launchd_service(
        project_dir=project_dir,
        interval_minutes=20,
        thread_limit=25,
        min_priority="high",
        no_openai=True,
        plist_dir=plist_dir,
    )
    plist = launchd_plist(service, project_dir=project_dir)

    assert plist["Label"] == "dk.local.aula-project.notify"
    assert plist["ProgramArguments"] == [
        "/opt/homebrew/bin/uv",
        "run",
        "aula-project",
        "notify-new",
        "--thread-limit",
        "25",
        "--min-priority",
        "high",
        "--no-openai",
    ]
    assert plist["WorkingDirectory"] == str(project_dir)
    assert plist["StartInterval"] == 1200


def test_write_launchd_plist_writes_valid_plist(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aula_project.service.shutil.which", lambda name: "/opt/homebrew/bin/uv")
    service = build_launchd_service(project_dir=tmp_path, plist_dir=tmp_path)

    path = write_launchd_plist(service, project_dir=tmp_path)

    assert path.exists()
    parsed = plistlib.loads(path.read_bytes())
    assert parsed["ProgramArguments"][:3] == ["/opt/homebrew/bin/uv", "run", "aula-project"]


def test_build_summary_launchd_service_plist_keeps_server_alive(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aula_project.service.shutil.which", lambda name: "/opt/homebrew/bin/uv")

    service = build_summary_launchd_service(
        project_dir=tmp_path,
        host="127.0.0.1",
        port=8765,
        thread_limit=20,
        result_limit=10,
        plist_dir=tmp_path,
    )
    plist = launchd_plist(service, project_dir=tmp_path)

    assert service.label == "dk.local.aula-project.summary"
    assert plist["ProgramArguments"] == [
        "/opt/homebrew/bin/uv",
        "run",
        "aula-project",
        "summary-server",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "--thread-limit",
        "20",
        "--limit",
        "10",
    ]
    assert plist["KeepAlive"] is True
    assert "StartInterval" not in plist


def test_summary_html_renders_important_threads() -> None:
    html = build_summary_html(
        {
            "checked_at": "2026-05-01T08:00:00Z",
            "auth": {"message": "Cached Aula token is reusable."},
            "profile": {"display_name": "Kasper"},
            "important_threads": [
                {
                    "thread": {
                        "thread_id": "thread-1",
                        "title": "Tur på fredag",
                        "last_message_at": "2026-05-01T07:30:00Z",
                    },
                    "level": "medium",
                    "score": 5,
                    "signals": [{"signal": "response_requested"}],
                    "messages": [
                        {
                            "sender_name": "Lærer",
                            "sent_at": "2026-05-01T07:30:00Z",
                            "body_text": "Husk madpakke og regntøj.",
                            "attachments": [{"filename": "program.pdf"}],
                        }
                    ],
                }
            ],
        }
    )

    assert "Aula Summary" in html
    assert "Tur på fredag" in html
    assert "2026-05-01 07:30" in html
    assert 'class="thread-time"' in html
    assert '<details class="message-full-text">' in html
    assert "<summary>Full text</summary>" in html
    assert "Husk madpakke og regntøj." in html
    assert "program.pdf" in html
    assert "response requested" in html


def test_summary_html_uses_message_timestamp_when_thread_timestamp_is_missing() -> None:
    html = build_summary_html(
        {
            "checked_at": "2026-05-01T08:00:00Z",
            "auth": {"message": "Cached Aula token is reusable."},
            "profile": {"display_name": "Kasper"},
            "important_threads": [
                {
                    "thread": {
                        "thread_id": "thread-1",
                        "title": "Tur på fredag",
                    },
                    "level": "medium",
                    "score": 5,
                    "signals": [],
                    "messages": [
                        {
                            "sender_name": "Lærer",
                            "sent_at": "2026-05-01T07:30:00Z",
                            "body_text": "Husk madpakke og regntøj.",
                            "attachments": [],
                        }
                    ],
                }
            ],
        }
    )

    assert "2026-05-01 07:30" in html


def test_summary_payload_cache_serves_stale_payload_after_error(tmp_path: Path) -> None:
    cache = SummaryPayloadCache(tmp_path / "summary-cache.json", ttl_seconds=0)
    payload = {
        "checked_at": "2026-05-01T08:00:00Z",
        "auth": {"message": "Cached Aula token is reusable."},
        "profile": {"display_name": "Kasper"},
        "important_threads": [],
    }
    cache._save_persisted(payload)

    cached = cache._with_cache_status(payload, status="stale", error="HTTP 429")

    assert cached["summary_cache"]["status"] == "stale"
    assert cached["summary_cache"]["cached_at"] == "2026-05-01T08:00:00Z"
    assert cached["summary_cache"]["error"] == "HTTP 429"
