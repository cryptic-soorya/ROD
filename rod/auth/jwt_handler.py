"""
auth/jwt_handler.py
OWNER: Teammate A

Responsibilities:
- generate_user_token(user_id, scopes, expires_in_minutes=60) -> str
    Creates a signed HS256 JWT for a human user session.
- generate_agent_token(agent_id, scopes) -> str
    Creates a signed HS256 JWT for an agent service. Expiry is hardcoded
    to AGENT_TOKEN_MINUTES and is NOT caller-configurable — this is what
    makes the SRS 2.1.2 cap non-negotiable rather than convention-based.
- verify_token(token: str) -> dict
    Decodes and validates a JWT. Raises HTTPException on expiry or bad signature.
- check_scope(token_payload: dict, required_scope: str) -> bool
    Called TWICE per tool call — once at MCP server startup, once per tool call
    before any DB query.

Key rules:
- JWT_SECRET comes from environment variable — never hardcoded.
- Agent service tokens NEVER appear in LLM context window.
- Max agent token expiry: 30 minutes (non-negotiable per SRS 2.1.2).
"""

import os
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from logging_config import get_logger

logger = get_logger("auth.jwt_handler")

# Fallback is for local dev only. Production/staging environments must
# inject JWT_SECRET via [secrets manager / k8s secret / CI env — fill in
# where this is actually enforced]. This file does not itself guarantee
# the fallback can't be reached outside local dev.
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")

ALGORITHM = "HS256"

# Token lifetime constants
USER_TOKEN_MINUTES  = 60
AGENT_TOKEN_MINUTES = 30   # hard cap per SRS 2.1.2 — not a default, a ceiling

_bearer = HTTPBearer()

# ── Internal helper ───────────────────────────────────────────────────────────

def _encode(
    subject: str,
    scopes: list[str],
    minutes: int,
    role: str | None = None,
    store_id: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub":    subject,
        "scopes": scopes,
        "iat":    now,
        "exp":    now + timedelta(minutes=minutes),
    }
    # Only human user sessions carry role/store_id — agent tokens
    # (generate_agent_token) never pass these, so omit rather than write
    # null claims onto every agent token.
    if role is not None:
        payload["role"] = role
    if store_id is not None:
        payload["store_id"] = store_id
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


# ── Token generation ──────────────────────────────────────────────────────────

def generate_user_token(
    user_id: str,
    scopes: list[str],
    expires_in_minutes: int = USER_TOKEN_MINUTES,
    role: str | None = None,
    store_id: str | None = None,
) -> str:
    """
    Creates a signed HS256 JWT for a human user session.
    Caller may request any expiry; there is no hard ceiling for user tokens
    beyond what's passed in.

    role and store_id are embedded as top-level JWT claims (not just used to
    derive `scopes`) so downstream routes — e.g. investigations/router.py's
    Store Manager access-control check — can read them directly off the
    verified token without a second DB lookup.
    """
    return _encode(user_id, scopes, expires_in_minutes, role=role, store_id=store_id)


def generate_agent_token(agent_id: str, scopes: list[str]) -> str:
    """
    Creates a signed HS256 JWT for an agent service.

    Expiry is intentionally NOT a parameter. It is hardcoded to
    AGENT_TOKEN_MINUTES (30) so this cap cannot be bypassed by a caller
    passing a larger value, per SRS 2.1.2.
    """
    return _encode(agent_id, scopes, AGENT_TOKEN_MINUTES)


# ── Token verification (FastAPI dependency) ───────────────────────────────────

def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency. Decodes and validates the Bearer JWT from the
    Authorization header. Raises 401 on expiry or invalid signature.
    Returns the decoded payload dict.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning(
            "bearer token expired",
            extra={"event": "auth_denied", "error_type": "ExpiredSignatureError"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        logger.warning(
            f"bearer token invalid ({type(exc).__name__})",
            extra={"event": "auth_denied", "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Scope check ───────────────────────────────────────────────────────────────

def check_scope(token_payload: dict, required_scope: str) -> bool:
    """
    Returns True if required_scope is present in the token's scopes list.
    Called before every MCP tool invocation (SRS Section 3.1).
    Does NOT raise — callers decide how to handle a False return.

    NOTE: this trusts token_payload as-is. Only ever pass a payload that
    has already been through verify_token() (i.e. signature-checked) —
    never a dict decoded without verification.
    """
    scopes = token_payload.get("scopes", [])
    return required_scope in scopes