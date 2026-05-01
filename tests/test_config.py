from __future__ import annotations

from aula_project.config import load_settings


def test_load_settings_reads_notification_and_timeout_values(monkeypatch) -> None:
    monkeypatch.setenv("AULA_MITID_USERNAME", "user")
    monkeypatch.setenv("AULA_NOTIFY_URLS", "pover://one ntfy://topic")
    monkeypatch.setenv("AULA_NOTIFY_MIN_PRIORITY", "high")
    monkeypatch.setenv("AULA_REQUEST_TIMEOUT_SECONDS", "12.5")

    settings = load_settings(env_file=None)

    assert settings.notify_urls == ["pover://one", "ntfy://topic"]
    assert settings.notify_min_priority == "high"
    assert settings.request_timeout_seconds == 12.5
