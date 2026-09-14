from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import Settings
from app.db import init_db, session_scope
from app.main import create_app


@pytest.fixture
def test_settings(tmp_path):
    return Settings(
        bale_bot_token="test-bale-token",
        bale_webhook_secret="test-webhook-secret",
        avalai_api_key="test-avalai-key",
        avalai_transcribe_model="whisper-1",
        avalai_text_model="test-model",
        session_secret="test-session-secret-please-change",
        app_base_url="https://self.example",
        database_path=str(tmp_path / "test.sqlite3"),
    )


@pytest.fixture
def test_client(test_settings):
    with TestClient(create_app(test_settings)) as client:
        yield client


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'session.sqlite3'}")
    init_db(engine)
    with session_scope(engine) as db_session:
        yield db_session
