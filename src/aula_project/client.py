from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any

from aula_project.auth import authenticated_client, authenticated_session, inspect_token_cache
from aula_project.config import Settings
from aula_project.message_cache import MessageCache, load_message_cache, save_message_cache
from aula_project.models import AuthCacheStatus, AuthResult, MessageItem, MessageThread, Profile, ThreadAssessment
from aula_project.normalize import normalize_messages, normalize_profile, normalize_threads
from aula_project.openai_review import review_new_messages_with_openai
from aula_project.scan_state import ScanState, load_scan_state, save_scan_state, utc_now_iso
from aula_project.scheduled_review import ScheduledReviewResult, build_new_thread_messages, mark_reviewed
from aula_project.triage import assess_thread, rank_threads


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _serialize_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=_json_default)


def _validate_since_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    candidate = f"{normalized[:-1]}+00:00" if normalized.endswith("Z") else normalized
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"--since must be an ISO timestamp, got {value!r}") from exc
    return normalized


def _review_state_for_since(state: ScanState, since: str | None) -> ScanState:
    since = _validate_since_timestamp(since)
    if since is None:
        return state
    return ScanState(last_checked_at=since, seen_message_ids=set())


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

    def _cached_messages_for_thread(
        self,
        cache: MessageCache,
        thread: MessageThread,
    ) -> list[MessageItem] | None:
        return cache.get_messages(thread)

    async def _messages_for_thread(
        self,
        session_client: Any,
        thread: MessageThread,
        *,
        cache: MessageCache,
        save_raw: bool,
    ) -> tuple[list[MessageItem], bool]:
        cached_messages = self._cached_messages_for_thread(cache, thread)
        if cached_messages is not None:
            return cached_messages, False

        raw_messages = await session_client.get_messages_for_thread(thread.thread_id)
        self._save_raw(f"thread-{thread.thread_id}-messages", raw_messages, enabled=save_raw)
        messages = normalize_messages(raw_messages or [], thread_id=thread.thread_id)
        cache.set_messages(thread, messages)
        return messages, True

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

            message_cache = load_message_cache(self.settings.message_cache_path)
            cache_changed = False
            assessments: list[ThreadAssessment] = []
            for thread in threads:
                messages, fetched = await self._messages_for_thread(
                    session.client,
                    thread,
                    cache=message_cache,
                    save_raw=save_raw,
                )
                cache_changed = cache_changed or fetched
                assessments.append(assess_thread(thread, messages))

        if cache_changed:
            save_message_cache(self.settings.message_cache_path, message_cache)

        ranked = rank_threads(assessments, include_low=include_low)
        if result_limit is not None:
            return ranked[:result_limit]
        return ranked

    async def review_new_messages(
        self,
        *,
        thread_limit: int | None = None,
        since: str | None = None,
        call_openai: bool = True,
        update_state: bool = True,
        save_raw: bool = False,
    ) -> ScheduledReviewResult:
        state = load_scan_state(self.settings.scan_state_path)
        review_state = _review_state_for_since(state, since)
        checked_at = utc_now_iso()
        async with authenticated_session(self.settings) as session:
            raw_threads = await session.client.get_message_threads()
            self._save_raw("message-threads", raw_threads, enabled=save_raw)
            threads = normalize_threads(raw_threads or [])
            if thread_limit is not None:
                threads = threads[:thread_limit]

            message_cache = load_message_cache(self.settings.message_cache_path)
            cache_changed = False
            messages_by_thread_id: dict[str, list[MessageItem]] = {}
            for thread in threads:
                messages, fetched = await self._messages_for_thread(
                    session.client,
                    thread,
                    cache=message_cache,
                    save_raw=save_raw,
                )
                cache_changed = cache_changed or fetched
                messages_by_thread_id[thread.thread_id] = messages

        if cache_changed:
            save_message_cache(self.settings.message_cache_path, message_cache)

        items = build_new_thread_messages(threads, messages_by_thread_id, review_state)
        openai_review = None
        if call_openai and items:
            openai_review = review_new_messages_with_openai(items, model=self.settings.openai_model)

        state_updated = False
        if update_state:
            next_state = mark_reviewed(state, items, checked_at=checked_at)
            save_scan_state(self.settings.scan_state_path, next_state)
            state_updated = True

        return ScheduledReviewResult(
            previous_last_checked_at=review_state.last_checked_at,
            checked_at=checked_at,
            new_thread_count=len(items),
            new_message_count=sum(len(item.messages) for item in items),
            items=items,
            openai_review=openai_review,
            state_updated=state_updated,
        )
