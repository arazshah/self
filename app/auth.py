from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DashboardSession, DashboardToken


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class AuthService:
    token_ttl = timedelta(minutes=10)
    session_ttl = timedelta(days=14)

    def __init__(self, session: Session, secret: str, base_url: str):
        self.session = session
        self.secret = secret.encode("utf-8")
        self.base_url = base_url.rstrip("/")

    def _hash(self, value: str) -> str:
        return hmac.new(self.secret, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def create_dashboard_token(self, user_id: int, now: datetime) -> str:
        raw = secrets.token_urlsafe(32)
        self.session.add(
            DashboardToken(
                user_id=user_id,
                token_hash=self._hash(raw),
                expires_at=_aware(now) + self.token_ttl,
            )
        )
        self.session.flush()
        return raw

    def dashboard_url(self, raw_token: str) -> str:
        return f"{self.base_url}/auth/claim/{raw_token}"

    def consume_dashboard_token(self, raw_token: str, now: datetime) -> int | None:
        token = self.session.scalar(
            select(DashboardToken).where(DashboardToken.token_hash == self._hash(raw_token))
        )
        current = _aware(now)
        if token is None or token.consumed_at is not None or _aware(token.expires_at) <= current:
            return None
        token.consumed_at = current
        self.session.flush()
        return token.user_id

    def create_session(self, user_id: int, now: datetime) -> tuple[str, str]:
        session_id = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        self.session.add(
            DashboardSession(
                user_id=user_id,
                session_hash=self._hash(session_id),
                csrf_hash=self._hash(csrf),
                expires_at=_aware(now) + self.session_ttl,
            )
        )
        self.session.flush()
        return session_id, csrf

    def get_session_user(self, session_id: str, now: datetime) -> int | None:
        item = self.session.scalar(
            select(DashboardSession).where(
                DashboardSession.session_hash == self._hash(session_id)
            )
        )
        if item is None or _aware(item.expires_at) <= _aware(now):
            return None
        return item.user_id

    def verify_csrf(self, session_id: str, csrf: str, now: datetime) -> bool:
        item = self.session.scalar(
            select(DashboardSession).where(
                DashboardSession.session_hash == self._hash(session_id)
            )
        )
        if item is None or _aware(item.expires_at) <= _aware(now):
            return False
        return hmac.compare_digest(item.csrf_hash, self._hash(csrf))

    def delete_session(self, session_id: str) -> None:
        item = self.session.scalar(
            select(DashboardSession).where(
                DashboardSession.session_hash == self._hash(session_id)
            )
        )
        if item is not None:
            self.session.delete(item)
