"""
auth/user_store.py

Schema (from Supabase):
    eid         text PK
    name        text
    role        text
    username    text (unique-ish, has a fingerprint/index icon in the UI)
    pass_hash   text   -- sha256(password).hexdigest(), NOT bcrypt
    phone_no    text
    email       text
    address     text
    store_id    text   -- FK -> reference.stores.store_id 

Functions :
 
    1. _hash_password - used to has password using sha256
    2. _constant_time_eq - used for hash comparisons to help avoid timing leaks
    3. get_user_by_username - gets details from the rod_auth.user table of a particular user using the user name provided
    4. get_user_by_id - gets user details from rod_auth.user table using the eid provided 
    5. verify_password - verifies credentials during logins
"""

import os
import hashlib
import secrets

import psycopg2
import psycopg2.extras

from logging_config import get_logger
from db_pool import get_conn,put_conn

logger = get_logger("auth.user_store")

DB_DSN = os.getenv("ROD_AUTH_DB_URL", os.getenv("DATABASE_URL"))

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _constant_time_eq(a: str, b: str) -> bool:
    """Used for hash comparison to avoid timing leaks."""
    return secrets.compare_digest(a, b)


def get_user_by_username(username: str) -> dict | None:
    conn = get_conn(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT eid, name, role, username, pass_hash, store_id FROM rod_auth.user WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        put_conn(DB_DSN,conn)


def get_user_by_id(eid: str) -> dict | None:
    conn = get_conn(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT eid, name, role, username, pass_hash, store_id FROM rod_auth.user WHERE eid = %s",
                (eid,),
            )
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        put_conn(DB_DSN,conn)


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