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


def test_normalize_messages_supports_nested_sender_and_attachment_containers() -> None:
    messages = normalize_messages(
        [
            {
                "messageKey": "live-msg-2",
                "threadKey": "thread-live",
                "sender": {"displayName": "Lærer Line"},
                "created": "2026-04-29T08:15:00Z",
                "content_html": "<p>Husk idrætstøj</p><p>Medbring madpakke.</p>",
                "files": {"items": [{"fileId": "file-1", "fileName": "praktisk-info.pdf"}]},
            }
        ],
        thread_id="fallback-thread",
    )

    assert messages[0].message_id == "live-msg-2"
    assert messages[0].thread_id == "thread-live"
    assert messages[0].sender_name == "Lærer Line"
    assert messages[0].sent_at == "2026-04-29T08:15:00Z"
    assert messages[0].body_text == "Husk idrætstøj Medbring madpakke."
    assert messages[0].attachments[0].attachment_id == "file-1"
    assert messages[0].attachments[0].filename == "praktisk-info.pdf"
