import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

from logging_config import get_logger

from db_pool import get_conn, put_conn

logger = get_logger("auth.refresh_token")

DB_DSN = os.getenv("ROD_AUTH_DB_URL", os.getenv("DATABASE_URL"))
REFRESH_TOKEN_EXPIRE_DAYS = 7

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_refresh_token() -> str:
    """Generates a raw, high-entropy refresh token."""
    return secrets.token_urlsafe(64)


def store_refresh_token(user_id: str, token: str) -> None:
    token_hash = _hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    conn = get_conn(DB_DSN)
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
        put_conn(DB_DSN, conn)


def revoke_refresh_token(token: str) -> None:
    token_hash = _hash_token(token)

    conn = get_conn(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE rod_auth.refresh_tokens SET revoked = TRUE WHERE token_hash = %s",
                    (token_hash,),
                )
    finally:
        put_conn(DB_DSN, conn)


def revoke_all_user_tokens(user_id: str) -> None:
    """Kills every refresh token for a user — used on theft detection or logout-all."""
    conn = get_conn(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE rod_auth.refresh_tokens SET revoked = TRUE WHERE user_id = %s",
                    (user_id,),
                )
    finally:
        put_conn(DB_DSN, conn)


def is_refresh_token_valid(token: str) -> dict | None:
    """
    Returns the row dict if token is valid (exists, not revoked, not expired).
    Returns None if invalid.
    Raises TokenReuseError if a REVOKED token is presented (possible theft).
    """
    token_hash = _hash_token(token)

    conn = get_conn(DB_DSN)
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
        put_conn(DB_DSN, conn)


class TokenReuseError(Exception):
    """Raised when a revoked refresh token is presented again — signals possible theft."""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"Revoked refresh token reused for user_id={user_id}")