from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ScanState:
    last_checked_at: str | None = None
    seen_message_ids: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_checked_at": self.last_checked_at,
            "seen_message_ids": sorted(self.seen_message_ids),
        }


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_scan_state(path: Path) -> ScanState:
    if not path.exists():
        return ScanState()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ScanState()

    if not isinstance(raw, dict):
        return ScanState()

    seen_raw = raw.get("seen_message_ids", [])
    seen = {str(item) for item in seen_raw if item} if isinstance(seen_raw, list) else set()
    last_checked_at = raw.get("last_checked_at")
    return ScanState(
        last_checked_at=str(last_checked_at) if last_checked_at else None,
        seen_message_ids=seen,
    )


def save_scan_state(path: Path, state: ScanState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
