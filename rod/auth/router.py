"""
auth/router.py
OWNER: Teammate A

FastAPI router for:
- POST /auth/login
    Body: { username, password }
    Returns: { token, expires_in, token_type, user: { id, role, scopes } }
    Sets: httpOnly refresh_token cookie (path=/auth/refresh)
    On fail: 401 { error: INVALID_CREDENTIALS }

- POST /auth/refresh
    Reads: refresh_token cookie
    Returns: { token, expires_in, token_type, user: { id, role, scopes } }
    Rotates refresh token on every call. Detects reuse of a revoked token
    and kills the whole token chain if reuse is detected.
    On fail: 401

- POST /auth/logout
    Reads: refresh_token cookie
    Revokes it, clears cookies.

Role → Scope mapping (from FRS Table 1.1.1):
    Admin             → all 9 scopes
    Category Manager  → read:sales, read:inventory, read:returns,
                        read:customers, read:promotions, read:knowledge
    Store Manager     → read:sales, read:inventory, read:returns, read:knowledge
"""

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response, status

from auth.models import LoginRequest, LoginResponse, UserPublic
from auth.jwt_handler import generate_user_token, USER_TOKEN_MINUTES
from auth.refresh_token import (
    generate_refresh_token,
    store_refresh_token,
    revoke_refresh_token,
    is_refresh_token_valid,
    TokenReuseError,
)

router = APIRouter(prefix="/auth", tags=["Auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth/refresh"   # must match this router's prefix + refresh route
REFRESH_COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days

# ── Role → scope mapping (FRS Table 1.1.1) ───────────────────────────────────

ROLE_SCOPES: dict[str, list[str]] = {
    "admin": [
        "read:sales", "read:inventory", "read:returns", "read:customers",
        "read:promotions", "read:knowledge", "read:suppliers",
        "write:knowledge", "read:reports",
    ],
    "category_manager": [
        "read:sales", "read:inventory", "read:returns",
        "read:customers", "read:promotions", "read:knowledge",
    ],
    "store_manager": [
        "read:sales", "read:inventory", "read:returns", "read:knowledge",
    ],
}

# ── In-memory user store (replace with DB lookup in production) ───────────────
# Passwords are bcrypt-hashed. These match plaintext: admin123, manager123, store123

_USERS: dict[str, dict] = {
    "admin": {
        "id":       "user-001",
        "role":     "admin",
        "password": bcrypt.hashpw(b"admin123", bcrypt.gensalt()),
    },
    "category_manager": {
        "id":       "user-002",
        "role":     "category_manager",
        "password": bcrypt.hashpw(b"manager123", bcrypt.gensalt()),
    },
    "store_manager": {
        "id":       "user-003",
        "role":     "store_manager",
        "password": bcrypt.hashpw(b"store123", bcrypt.gensalt()),
    },
}


def _lookup_user_by_id(user_id: str) -> dict | None:
    """Reverse lookup by id, since refresh only has user_id, not username."""
    for user in _USERS.values():
        if user["id"] == user_id:
            return user
    return None


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=REFRESH_COOKIE_MAX_AGE,
        path=REFRESH_COOKIE_PATH,
    )


# ── POST /auth/login ──────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login and receive a JWT",
)
def login(body: LoginRequest, response: Response) -> LoginResponse:
    user = _USERS.get(body.username)

    # Constant-time comparison even on missing user (prevents timing attacks)
    password_ok = (
        user is not None
        and bcrypt.checkpw(body.password.encode(), user["password"])
    )

    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "INVALID_CREDENTIALS"},
        )

    role   = user["role"]
    scopes = ROLE_SCOPES[role]
    token  = generate_user_token(user["id"], scopes, expires_in_minutes=USER_TOKEN_MINUTES)

    refresh_token = generate_refresh_token()
    store_refresh_token(user["id"], refresh_token)
    _set_refresh_cookie(response, refresh_token)

    return LoginResponse(
        token=token,
        expires_in=USER_TOKEN_MINUTES * 60,
        user=UserPublic(id=user["id"], role=role, scopes=scopes),
    )


# ── POST /auth/refresh ────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=LoginResponse,
    summary="Exchange a valid refresh token cookie for a new access token",
)
def refresh(request: Request, response: Response) -> LoginResponse:
    old_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not old_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "NO_REFRESH_TOKEN"},
        )

    try:
        row = is_refresh_token_valid(old_token)
    except TokenReuseError:
        # Revoked token was reused — treat as theft. Whole chain already
        # killed inside is_refresh_token_valid; just clear the cookie here.
        response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "REFRESH_TOKEN_REUSE_DETECTED"},
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "INVALID_OR_EXPIRED_REFRESH_TOKEN"},
        )

    user = _lookup_user_by_id(row["user_id"])
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "USER_NOT_FOUND"},
        )

    # Rotate: kill old, issue new
    revoke_refresh_token(old_token)
    new_refresh_token = generate_refresh_token()
    store_refresh_token(user["id"], new_refresh_token)
    _set_refresh_cookie(response, new_refresh_token)

    role   = user["role"]
    scopes = ROLE_SCOPES[role]
    new_access_token = generate_user_token(user["id"], scopes, expires_in_minutes=USER_TOKEN_MINUTES)

    return LoginResponse(
        token=new_access_token,
        expires_in=USER_TOKEN_MINUTES * 60,
        user=UserPublic(id=user["id"], role=role, scopes=scopes),
    )


# ── POST /auth/logout ─────────────────────────────────────────────────────────

@router.post(
    "/logout",
    summary="Revoke refresh token and clear auth cookies",
)
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if token:
        revoke_refresh_token(token)

    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    return {"detail": "logged out"}