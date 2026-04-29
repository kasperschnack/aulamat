from __future__ import annotations

import json
from pathlib import Path

from aula_project.models import MessageSource
from aula_project.normalize import normalize_profile, normalize_threads


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_normalize_profile_maps_child_context() -> None:
    profile = normalize_profile(_load_fixture("profile.json"))

    assert profile.profile_id == "guardian-1"
    assert profile.display_name == "Kasper Guardian"
    assert len(profile.children) == 1
    assert profile.children[0].child_id == "child-1"
    assert profile.children[0].institution_name == "Aula Friskole"


def test_normalize_threads_infers_provider_and_unread_state() -> None:
    threads = normalize_threads(_load_fixture("message_threads.json"))

    assert [thread.thread_id for thread in threads] == ["thread-1", "thread-2"]
    assert threads[0].unread is True
    assert threads[0].participants == ["Lærer Line", "Kasper Guardian"]
    assert threads[1].source is MessageSource.MEEBOOK


def test_normalize_threads_supports_live_aliases_and_string_booleans() -> None:
    threads = normalize_threads(
        [
            {
                "threadKey": "live-thread-1",
                "name": "Ændret afhentning",
                "recipients": [{"fullName": "Lærer Line"}],
                "lastMessageTimestamp": "2026-04-29T12:00:00Z",
                "isUnread": "false",
                "messagePreview": "Barnet skal hentes tidligere.",
            },
            {
                "conversationId": "live-thread-2",
                "subject": "Svar udbedes",
                "hasUnreadMessages": "ja",
            },
        ]
    )

    assert threads[0].thread_id == "live-thread-1"
    assert threads[0].title == "Ændret afhentning"
    assert threads[0].participants == ["Lærer Line"]
    assert threads[0].last_message_at == "2026-04-29T12:00:00Z"
    assert threads[0].unread is False
    assert threads[0].preview_text == "Barnet skal hentes tidligere."
    assert threads[1].thread_id == "live-thread-2"
    assert threads[1].unread is True
