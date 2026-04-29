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
    raw_capture_dir: Path | None
    auth_method: str = "app"
    default_limit: int = 10
    json_indent: int = 2


def _resolve_path(value: str | None, default: str) -> Path:
    chosen = value or default
    return Path(chosen).expanduser()


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

    return Settings(
        mitid_username=mitid_username,
        token_cache_path=_resolve_path(os.getenv("AULA_TOKEN_CACHE_PATH"), ".aula_tokens.json"),
        raw_capture_dir=raw_capture_dir,
        auth_method=os.getenv("AULA_AUTH_METHOD", "app").strip().lower() or "app",
        default_limit=int(os.getenv("AULA_MESSAGE_LIMIT", "10")),
        json_indent=int(os.getenv("AULA_JSON_INDENT", "2")),
    )
