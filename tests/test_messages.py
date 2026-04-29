from __future__ import annotations

import json
from pathlib import Path

from aula_project.normalize import normalize_messages


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_normalize_messages_extracts_html_text_and_attachments() -> None:
    messages = normalize_messages(_load_fixture("thread_messages_thread-1.json"), thread_id="thread-1")

    assert [message.message_id for message in messages] == ["msg-1", "msg-2"]
    assert messages[0].thread_id == "thread-1"
    assert messages[0].body_html == "<p>Vi ses <strong>i morgen</strong>.</p>"
    assert messages[0].body_text == "Vi ses i morgen."
    assert messages[0].attachments[0].filename == "invitation.pdf"
    assert messages[1].body_text == "Tak for beskeden"


def test_normalize_messages_supports_live_aula_content_html() -> None:
    messages = normalize_messages(_load_fixture("thread_messages_live_style.json"), thread_id="thread-live")

    assert messages[0].thread_id == "thread-live"
    assert messages[0].body_html == "<div>Svar senest i morgen kl. 14.</div>"
    assert messages[0].body_text == "Svar senest i morgen kl. 14."
