from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


DEFAULT_ENV_FILE = ".env"


@dataclass(slots=True)
class Settings:
    mitid_username: str
    token_cache_path: Path
    scan_state_path: Path
    raw_capture_dir: Path | None
    notify_urls: list[str]
    auth_method: str = "app"
    default_limit: int = 10
    json_indent: int = 2
    openai_model: str = "gpt-5.2"
    notify_min_priority: str = "medium"
    request_timeout_seconds: float = 60.0


def _resolve_path(value: str | None, default: str) -> Path:
    chosen = value or default
    return Path(chosen).expanduser()


def _split_notify_urls(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split() if item.strip()]


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return float(value)


def load_settings(
    env_file: str | None = DEFAULT_ENV_FILE,
    *,
    require_username: bool = True,
) -> Settings:
    if env_file:
        load_dotenv(env_file, override=False)

    mitid_username = os.getenv("AULA_MITID_USERNAME", "").strip()
    if require_username and not mitid_username:
        raise ValueError("Missing AULA_MITID_USERNAME. Set it in the environment or .env.")

    raw_capture_value = os.getenv("AULA_RAW_CAPTURE_DIR", "").strip()
    raw_capture_dir = Path(raw_capture_value).expanduser() if raw_capture_value else None
    notify_urls = _split_notify_urls(os.getenv("AULA_NOTIFY_URLS") or os.getenv("AULA_NOTIFY_URL"))

    return Settings(
        mitid_username=mitid_username,
        token_cache_path=_resolve_path(os.getenv("AULA_TOKEN_CACHE_PATH"), ".aula_tokens.json"),
        scan_state_path=_resolve_path(os.getenv("AULA_SCAN_STATE_PATH"), ".aula_scan_state.json"),
        raw_capture_dir=raw_capture_dir,
        notify_urls=notify_urls,
        auth_method=os.getenv("AULA_AUTH_METHOD", "app").strip().lower() or "app",
        default_limit=int(os.getenv("AULA_MESSAGE_LIMIT", "10")),
        json_indent=int(os.getenv("AULA_JSON_INDENT", "2")),
        openai_model=os.getenv("AULA_OPENAI_MODEL", "gpt-5.2").strip() or "gpt-5.2",
        notify_min_priority=os.getenv("AULA_NOTIFY_MIN_PRIORITY", "medium").strip().lower() or "medium",
        request_timeout_seconds=_float_env("AULA_REQUEST_TIMEOUT_SECONDS", 60.0),
    )
