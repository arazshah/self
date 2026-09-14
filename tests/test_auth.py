from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine

from app.auth import AuthService
from app.db import init_db, session_scope
from app.repositories import UserRepository


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.sqlite3'}")
    init_db(engine)
    return engine


def test_dashboard_token_expires_and_is_single_use(tmp_path):
    engine = _session(tmp_path)
    now = datetime(2026, 9, 14, 8, tzinfo=UTC)

    with session_scope(engine) as session:
        user = UserRepository(session).get_or_create_by_bale_chat(10, "A")
        auth = AuthService(session, "test-secret", "https://self.example")
        token = auth.create_dashboard_token(user.id, now)

        assert auth.consume_dashboard_token(token, now + timedelta(minutes=9)) == user.id
        assert auth.consume_dashboard_token(token, now + timedelta(minutes=9)) is None

        second_token = auth.create_dashboard_token(user.id, now)
        assert auth.consume_dashboard_token(second_token, now + timedelta(minutes=11)) is None


def test_session_is_bound_to_user_and_csrf_is_required(tmp_path):
    engine = _session(tmp_path)
    now = datetime(2026, 9, 14, 8, tzinfo=UTC)

    with session_scope(engine) as session:
        users = UserRepository(session)
        user = users.get_or_create_by_bale_chat(10, "A")
        other = users.get_or_create_by_bale_chat(20, "B")
        auth = AuthService(session, "test-secret", "https://self.example")
        session_id, csrf = auth.create_session(user.id, now)

        assert auth.get_session_user(session_id, now) == user.id
        assert auth.verify_csrf(session_id, csrf, now)
        assert not auth.verify_csrf(session_id, "wrong", now)
        assert auth.get_session_user(session_id, now) != other.id
