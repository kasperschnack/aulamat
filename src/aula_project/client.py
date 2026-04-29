from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any

from aula_project.auth import authenticated_client, authenticated_session, inspect_token_cache
from aula_project.config import Settings
from aula_project.models import AuthCacheStatus, AuthResult, MessageItem, MessageThread, Profile, ThreadAssessment
from aula_project.normalize import normalize_messages, normalize_profile, normalize_threads
from aula_project.triage import assess_thread, rank_threads


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _serialize_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=_json_default)


@dataclass(slots=True)
class RawCaptureStore:
    base_dir: Path

    def save(self, label: str, payload: Any) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_label = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "payload"
        path = self.base_dir / f"{timestamp}-{safe_label}.json"
        path.write_text(_serialize_json(payload), encoding="utf-8")
        return path


class AulaDataClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.capture_store = (
            RawCaptureStore(settings.raw_capture_dir) if settings.raw_capture_dir is not None else None
        )

    def _save_raw(self, label: str, payload: Any, enabled: bool) -> None:
        if enabled and self.capture_store is not None:
            self.capture_store.save(label, payload)

    def get_auth_cache_status(self) -> AuthCacheStatus:
        return inspect_token_cache(self.settings.token_cache_path)

    async def login(self, *, save_raw: bool = False) -> tuple[Profile, AuthResult]:
        async with authenticated_session(self.settings) as session:
            raw_profile = await session.client.get_profile()
            auth_result = session.auth_result
        self._save_raw("profile", raw_profile, enabled=save_raw)
        return normalize_profile(raw_profile), auth_result

    async def get_profile(self, *, save_raw: bool = False) -> Profile:
        async with authenticated_client(self.settings) as client:
            raw_profile = await client.get_profile()
        self._save_raw("profile", raw_profile, enabled=save_raw)
        return normalize_profile(raw_profile)

    async def list_threads(self, *, limit: int | None = None, save_raw: bool = False) -> list[MessageThread]:
        async with authenticated_client(self.settings) as client:
            raw_threads = await client.get_message_threads()
        self._save_raw("message-threads", raw_threads, enabled=save_raw)
        threads = normalize_threads(raw_threads or [])
        if limit is not None:
            return threads[:limit]
        return threads

    async def get_messages(
        self,
        thread_id: str,
        *,
        save_raw: bool = False,
    ) -> list[MessageItem]:
        async with authenticated_client(self.settings) as client:
            raw_messages = await client.get_messages_for_thread(thread_id)
        self._save_raw(f"thread-{thread_id}-messages", raw_messages, enabled=save_raw)
        return normalize_messages(raw_messages or [], thread_id=thread_id)

    async def list_important_threads(
        self,
        *,
        thread_limit: int | None = None,
        result_limit: int | None = None,
        include_low: bool = False,
        save_raw: bool = False,
    ) -> list[ThreadAssessment]:
        async with authenticated_session(self.settings) as session:
            raw_threads = await session.client.get_message_threads()
            self._save_raw("message-threads", raw_threads, enabled=save_raw)
            threads = normalize_threads(raw_threads or [])
            if thread_limit is not None:
                threads = threads[:thread_limit]

            assessments: list[ThreadAssessment] = []
            for thread in threads:
                raw_messages = await session.client.get_messages_for_thread(thread.thread_id)
                self._save_raw(f"thread-{thread.thread_id}-messages", raw_messages, enabled=save_raw)
                messages = normalize_messages(raw_messages or [], thread_id=thread.thread_id)
                assessments.append(assess_thread(thread, messages))

        ranked = rank_threads(assessments, include_low=include_low)
        if result_limit is not None:
            return ranked[:result_limit]
        return ranked
