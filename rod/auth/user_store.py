"""
auth/user_store.py

DB-backed replacement for the old in-memory _USERS dict in router.py.
Queries rod_auth.user (same Postgres DB as rod_auth.refresh_tokens).

Schema (from Supabase):
    eid         text PK
    name        text
    role        text
    username    text (unique-ish, has a fingerprint/index icon in the UI)
    pass_hash   text   -- sha256(password).hexdigest(), NOT bcrypt
    phone_no    text
    email       text
    address     text
"""

import os
import hashlib
import secrets

import psycopg2
import psycopg2.extras

from logging_config import get_logger

logger = get_logger("auth.user_store")

DB_DSN = os.getenv("ROD_AUTH_DB_URL", os.getenv("DATABASE_URL"))


def _get_conn() -> psycopg2.extensions.connection:
    return psycopg2.connect(DB_DSN, cursor_factory=psycopg2.extras.RealDictCursor)


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _constant_time_eq(a: str, b: str) -> bool:
    """Use this instead of == for hash comparison to avoid timing leaks."""
    return secrets.compare_digest(a, b)


def get_user_by_username(username: str) -> dict | None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT eid, name, role, username, pass_hash FROM rod_auth.user WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(eid: str) -> dict | None:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT eid, name, role, username, pass_hash FROM rod_auth.user WHERE eid = %s",
                (eid,),
            )
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def verify_password(username: str, password: str) -> dict | None:
    """
    Returns the user row dict if username exists and password matches.
    Returns None otherwise. Always hashes something even on missing user
    (constant-time-ish against username enumeration via timing).
    """
    user = get_user_by_username(username)
    candidate_hash = _hash_password(password)

    if user is None:
        # Burn the same amount of time as a real comparison would take,
        # against a dummy hash, so a missing user isn't faster to detect.
        _constant_time_eq(candidate_hash, "0" * 64)
        return None

    if not _constant_time_eq(candidate_hash, user["pass_hash"]):
        return None

    return user