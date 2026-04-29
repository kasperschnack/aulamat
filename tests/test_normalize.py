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
