import pytest

from app.config import ConfigurationError, Settings


def test_settings_from_env_requires_secrets(monkeypatch):
    for name in (
        "BALE_BOT_TOKEN",
        "BALE_WEBHOOK_SECRET",
        "AVALAI_API_KEY",
        "AVALAI_TRANSCRIBE_MODEL",
        "AVALAI_TEXT_MODEL",
        "SESSION_SECRET",
        "APP_BASE_URL",
        "DATABASE_PATH",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ConfigurationError, match="BALE_BOT_TOKEN"):
        Settings.from_env()


def test_settings_from_env_parses_safe_defaults(monkeypatch):
    values = {
        "BALE_BOT_TOKEN": "bale",
        "BALE_WEBHOOK_SECRET": "webhook",
        "AVALAI_API_KEY": "avalai",
        "AVALAI_TRANSCRIBE_MODEL": "whisper-1",
        "AVALAI_TEXT_MODEL": "text-model",
        "SESSION_SECRET": "session-secret",
        "APP_BASE_URL": "https://self.araz.me",
        "DATABASE_PATH": "/data/self.sqlite3",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()

    assert settings.default_timezone == "Asia/Tehran"
    assert settings.raw_audio_retention_hours == 24
    assert settings.daily_digest_hour == 8
