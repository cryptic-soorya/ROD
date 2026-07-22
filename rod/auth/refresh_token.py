import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

from logging_config import get_logger

logger = get_logger("auth.refresh_token")

# SCHEMA NOTE (2026-07-20): migrated off the old local SQLite
# mcp_server/db/rod.db onto Postgres, schema `rod_auth`. Column names are
# unchanged (id/user_id/token_hash/expires_at/revoked/created_at) — id is
# an identity column there (has auto-increment, unlike orchestration.reports'
# text PK), so RETURNING/serial behavior works the same as before.
# user_id stays text: rod_auth.user's PK is `eid` (text), not an integer.
DB_DSN = os.getenv("ROD_AUTH_DB_URL", os.getenv("DATABASE_URL"))
REFRESH_TOKEN_EXPIRE_DAYS = 7


def _get_conn() -> psycopg2.extensions.connection:
    return psycopg2.connect(DB_DSN, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db() -> None:
    """
    No-op, kept only so `from auth.refresh_token import init_db` in main.py
    doesn't need to change. rod_auth.refresh_tokens is a real Postgres table
    managed in Supabase now — the app doesn't own its schema and shouldn't
    run CREATE TABLE against it.
    """
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_refresh_token() -> str:
    """Generates a raw, high-entropy refresh token (not yet stored)."""
    return secrets.token_urlsafe(64)


def store_refresh_token(user_id: str, token: str) -> None:
    token_hash = _hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO rod_auth.refresh_tokens
                       (user_id, token_hash, expires_at, revoked)
                       VALUES (%s, %s, %s, FALSE)""",
                    (user_id, token_hash, expires_at),
                )
    finally:
        conn.close()


def revoke_refresh_token(token: str) -> None:
    token_hash = _hash_token(token)

    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE rod_auth.refresh_tokens SET revoked = TRUE WHERE token_hash = %s",
                    (token_hash,),
                )
    finally:
        conn.close()


def revoke_all_user_tokens(user_id: str) -> None:
    """Kills every refresh token for a user — used on theft detection or logout-all."""
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE rod_auth.refresh_tokens SET revoked = TRUE WHERE user_id = %s",
                    (user_id,),
                )
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
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM rod_auth.refresh_tokens WHERE token_hash = %s",
                (token_hash,),
            )
            row = cur.fetchone()

        if row is None:
            return None

        if row["revoked"]:
            # Reuse detection: someone presented a token that's already dead.
            # Could be the real user replaying an old request, but treat as theft signal.
            logger.error(
                f"revoked refresh token reused for user_id={row['user_id']} — killing token chain",
                extra={"event": "refresh_token_reuse", "error_type": "TokenReuseError"},
            )
            revoke_all_user_tokens(row["user_id"])
            raise TokenReuseError(row["user_id"])

        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < datetime.now(timezone.utc):
            return None

        return dict(row)
    finally:
        conn.close()


class TokenReuseError(Exception):
    """Raised when a revoked refresh token is presented again — signals possible theft."""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"Revoked refresh token reused for user_id={user_id}")