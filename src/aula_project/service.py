from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import plistlib
import shutil
from typing import Any


DEFAULT_SERVICE_LABEL = "dk.local.aula-project.notify"
DEFAULT_SUMMARY_SERVICE_LABEL = "dk.local.aula-project.summary"
DEFAULT_SUMMARY_SERVER_PORT = 8767


@dataclass(slots=True)
class LaunchdService:
    label: str
    plist_path: Path
    interval_minutes: int | None
    command: list[str]
    keep_alive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "plist_path": str(self.plist_path),
            "interval_minutes": self.interval_minutes,
            "command": self.command,
            "keep_alive": self.keep_alive,
        }


def default_launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def build_launchd_service(
    *,
    project_dir: Path,
    interval_minutes: int = 20,
    thread_limit: int | None = None,
    min_priority: str | None = None,
    no_openai: bool = False,
    label: str = DEFAULT_SERVICE_LABEL,
    plist_dir: Path | None = None,
) -> LaunchdService:
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be at least 1.")

    uv_executable = shutil.which("uv") or "uv"
    command = [uv_executable, "run", "aula-project", "notify-new"]
    if thread_limit is not None:
        command.extend(["--thread-limit", str(thread_limit)])
    if min_priority is not None:
        command.extend(["--min-priority", min_priority])
    if no_openai:
        command.append("--no-openai")

    resolved_plist_dir = plist_dir or default_launch_agents_dir()
    return LaunchdService(
        label=label,
        plist_path=resolved_plist_dir / f"{label}.plist",
        interval_minutes=interval_minutes,
        command=command,
    )


def build_summary_launchd_service(
    *,
    project_dir: Path,
    host: str = "127.0.0.1",
    port: int = DEFAULT_SUMMARY_SERVER_PORT,
    thread_limit: int | None = None,
    result_limit: int | None = 10,
    label: str = DEFAULT_SUMMARY_SERVICE_LABEL,
    plist_dir: Path | None = None,
) -> LaunchdService:
    uv_executable = shutil.which("uv") or "uv"
    command = [
        uv_executable,
        "run",
        "aula-project",
        "summary-server",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if thread_limit is not None:
        command.extend(["--thread-limit", str(thread_limit)])
    if result_limit is not None:
        command.extend(["--limit", str(result_limit)])

    resolved_plist_dir = plist_dir or default_launch_agents_dir()
    return LaunchdService(
        label=label,
        plist_path=resolved_plist_dir / f"{label}.plist",
        interval_minutes=None,
        command=command,
        keep_alive=True,
    )


def launchd_plist(service: LaunchdService, *, project_dir: Path) -> dict[str, Any]:
    log_stem = service.label.replace(".", "_")
    log_path = project_dir / f".{log_stem}.log"
    error_log_path = project_dir / f".{log_stem}.err.log"
    payload: dict[str, Any] = {
        "Label": service.label,
        "ProgramArguments": service.command,
        "WorkingDirectory": str(project_dir),
        "RunAtLoad": True,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(error_log_path),
    }
    if service.interval_minutes is not None:
        payload["StartInterval"] = service.interval_minutes * 60
    if service.keep_alive:
        payload["KeepAlive"] = True
    return payload


def write_launchd_plist(service: LaunchdService, *, project_dir: Path) -> Path:
    service.plist_path.parent.mkdir(parents=True, exist_ok=True)
    service.plist_path.write_bytes(plistlib.dumps(launchd_plist(service, project_dir=project_dir)))
    return service.plist_path
