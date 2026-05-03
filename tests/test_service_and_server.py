from __future__ import annotations

from pathlib import Path
import plistlib

from aula_project.service import build_launchd_service, launchd_plist, write_launchd_plist
from aula_project.summary_server import build_summary_html


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


def test_summary_html_renders_important_threads() -> None:
    html = build_summary_html(
        {
            "checked_at": "2026-05-01T08:00:00Z",
            "auth": {"message": "Cached Aula token is reusable."},
            "profile": {"display_name": "Kasper"},
            "important_threads": [
                {
                    "thread": {"thread_id": "thread-1", "title": "Tur på fredag"},
                    "level": "medium",
                    "score": 5,
                    "signals": [{"signal": "response_requested"}],
                }
            ],
        }
    )

    assert "Aula Summary" in html
    assert "Tur på fredag" in html
    assert "response requested" in html
