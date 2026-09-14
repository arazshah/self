from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    """Raised when a required production setting is missing."""


@dataclass(frozen=True, slots=True)
class Settings:
    bale_bot_token: str
    bale_webhook_secret: str
    avalai_api_key: str
    avalai_transcribe_model: str
    avalai_text_model: str
    session_secret: str
    app_base_url: str
    database_path: str
    default_timezone: str = "Asia/Tehran"
    raw_audio_retention_hours: int = 24
    daily_digest_hour: int = 8

    @classmethod
    def from_env(cls) -> Settings:
        required = {
            "BALE_BOT_TOKEN": "bale_bot_token",
            "BALE_WEBHOOK_SECRET": "bale_webhook_secret",
            "AVALAI_API_KEY": "avalai_api_key",
            "AVALAI_TRANSCRIBE_MODEL": "avalai_transcribe_model",
            "AVALAI_TEXT_MODEL": "avalai_text_model",
            "SESSION_SECRET": "session_secret",
            "APP_BASE_URL": "app_base_url",
            "DATABASE_PATH": "database_path",
        }
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise ConfigurationError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        return cls(
            **{field: os.environ[name] for name, field in required.items()},
            default_timezone=os.getenv("DEFAULT_TIMEZONE", "Asia/Tehran"),
            raw_audio_retention_hours=int(
                os.getenv("RAW_AUDIO_RETENTION_HOURS", "24")
            ),
            daily_digest_hour=int(os.getenv("DAILY_DIGEST_HOUR", "8")),
        )
