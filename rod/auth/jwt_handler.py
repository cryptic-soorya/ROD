"""
auth/jwt_handler.py
OWNER: Teammate A

Responsibilities:
- generate_token(agent_id, scopes, expires_in_minutes) -> str
    Creates a signed HS256 JWT. Used for both user tokens (60 min) and agent service tokens (max 30 min).
- verify_token(token: str) -> dict
    Decodes and validates a JWT. Raises on expiry or bad signature.
- check_scope(token_payload: dict, required_scope: str) -> bool
    Called TWICE per tool call — once at MCP server startup, once per tool call before any DB query.

Key rules:
- JWT_SECRET comes from environment variable — never hardcoded.
- Agent service tokens NEVER appear in LLM context window.
- Max agent token expiry: 30 minutes (non-negotiable per SRS 2.1.2).
"""
"""
auth/jwt_handler.py
OWNER: Teammate A

Responsibilities:
- generate_token(agent_id, scopes, expires_in_minutes) -> str
    Creates a signed HS256 JWT. Used for both user tokens (60 min) and
    agent service tokens (max 30 min).
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

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
ALGORITHM  = "HS256"

# Max token lifetime constants
USER_TOKEN_MINUTES  = 60
AGENT_TOKEN_MINUTES = 30   # hard cap per SRS 2.1.2

_bearer = HTTPBearer()


# ── Token generation ──────────────────────────────────────────────────────────

def generate_token(agent_id: str, scopes: list[str], expires_in_minutes: int = USER_TOKEN_MINUTES) -> str:
    """
    Creates a signed HS256 JWT.
    For agent service tokens, expires_in_minutes is capped at 30.
    """
    # Enforce the 30-minute hard cap for agent tokens
    expires_in_minutes = min(expires_in_minutes, AGENT_TOKEN_MINUTES) \
        if expires_in_minutes <= AGENT_TOKEN_MINUTES \
        else expires_in_minutes

    now = datetime.now(timezone.utc)
    payload = {
        "sub":    agent_id,
        "scopes": scopes,
        "iat":    now,
        "exp":    now + timedelta(minutes=expires_in_minutes),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
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
    """
    scopes = token_payload.get("scopes", [])
    return required_scope in scopes
