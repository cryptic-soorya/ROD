import sqlite3
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

import os
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "db", "rod.db")
DB_PATH = os.path.abspath(DB_PATH)
REFRESH_TOKEN_EXPIRE_DAYS = 7


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_refresh_token() -> str:
    """Generates a raw, high-entropy refresh token (not yet stored)."""
    return secrets.token_urlsafe(64)


def store_refresh_token(user_id: int, token: str) -> None:
    token_hash = _hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at, revoked)
            VALUES (?, ?, ?, 0)
            """,
            (user_id, token_hash, expires_at.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def revoke_refresh_token(token: str) -> None:
    token_hash = _hash_token(token)

    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?",
            (token_hash,),
        )
        conn.commit()
    finally:
        conn.close()


def revoke_all_user_tokens(user_id: int) -> None:
    """Kills every refresh token for a user — used on theft detection or logout-all."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def is_refresh_token_valid(token: str) -> dict | None:
    """
    Returns the row dict if token is valid (exists, not revoked, not expired).
    Returns None if invalid.
    Raises TokenReuseError if a REVOKED token is presented (possible theft).
    """
    token_hash = _hash_token(token)

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()

        if row is None:
            return None

        if row["revoked"]:
            # Reuse detection: someone presented a token that's already dead.
            # Could be the real user replaying an old request, but treat as theft signal.
            revoke_all_user_tokens(row["user_id"])
            raise TokenReuseError(row["user_id"])

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < datetime.now(timezone.utc):
            return None

        return dict(row)
    finally:
        conn.close()


class TokenReuseError(Exception):
    """Raised when a revoked refresh token is presented again — signals possible theft."""
    def __init__(self, user_id: int):
        self.user_id = user_id
        super().__init__(f"Revoked refresh token reused for user_id={user_id}")