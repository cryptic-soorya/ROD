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
    Manager           → read:sales, read:inventory, read:returns, read:knowledge

NOTE (2026-07-23): user lookup migrated from in-memory _USERS to
rod_auth.user via auth/user_store.py. eid is the user's PK (text).

NOTE (2026-07-27): category_manager and store_manager roles were collapsed
into a single "manager" role (see ROLE_SCOPES below) — rod_auth.user.role
now only stores "admin" or "manager". store_id is now a column on
rod_auth.user (FK -> reference.stores.store_id) and is embedded as a JWT
claim (see auth/jwt_handler.py's generate_user_token) so
investigations/router.py can scope a manager's results to their own store.
"""

from fastapi import APIRouter, HTTPException, Request, Response, status

from auth.models import LoginRequest, LoginResponse, UserPublic
from auth.jwt_handler import generate_user_token, USER_TOKEN_MINUTES
from auth.user_store import verify_password, get_user_by_id
from auth.refresh_token import (
    generate_refresh_token,
    store_refresh_token,
    revoke_refresh_token,
    is_refresh_token_valid,
    TokenReuseError,
)
from logging_config import get_logger

logger = get_logger("auth.router")

router = APIRouter(prefix="/auth", tags=["Auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth/refresh"   # must match this router's prefix + refresh route
REFRESH_COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days

# ── Role → scope mapping (FRS Table 1.1.1) ───────────────────────────────────
# NOTE: keys here must exactly match the `role` values stored in
# rod_auth.user.role. Verify actual stored values match these strings
# (admin / category_manager / store_manager) — if the DB uses different
# casing/spelling, either fix the DB values or update this dict.

ROLE_SCOPES: dict[str, list[str]] = {
    "admin": [
        "read:sales", "read:inventory", "read:returns", "read:customers",
        "read:promotions", "read:knowledge", "read:suppliers",
        "write:knowledge", "read:reports",
    ],
    "manager": [
        "read:sales", "read:inventory", "read:returns", "read:knowledge",
    ],
}


def _scopes_for_role(role: str) -> list[str]:
    scopes = ROLE_SCOPES.get(role)
    if scopes is None:
        logger.error(
            f"unmapped role={role!r} — no scopes defined, defaulting to empty",
            extra={"event": "role_scope_missing", "error_type": "UNMAPPED_ROLE"},
        )
        return []
    return scopes


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
    user = verify_password(body.username, body.password)

    if user is None:
        logger.warning(
            f"login failed for username={body.username!r}",
            extra={"event": "login_failed", "error_type": "INVALID_CREDENTIALS"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "INVALID_CREDENTIALS"},
        )

    role   = user["role"]
    scopes = _scopes_for_role(role)
    token  = generate_user_token(
        user["eid"], scopes, expires_in_minutes=USER_TOKEN_MINUTES,
        role=role, store_id=user.get("store_id"),
    )

    refresh_token = generate_refresh_token()
    store_refresh_token(user["eid"], refresh_token)
    _set_refresh_cookie(response, refresh_token)

    return LoginResponse(
        token=token,
        expires_in=USER_TOKEN_MINUTES * 60,
        user=UserPublic(id=user["eid"], role=role, scopes=scopes),
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
        logger.warning(
            "refresh attempted with no refresh_token cookie",
            extra={"event": "refresh_failed", "error_type": "NO_REFRESH_TOKEN"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "NO_REFRESH_TOKEN"},
        )

    try:
        row = is_refresh_token_valid(old_token)
    except TokenReuseError:
        # Revoked token was reused — treat as theft. Whole chain already
        # killed (and logged) inside is_refresh_token_valid; just clear the
        # cookie here.
        logger.error(
            "refresh denied — reuse of revoked token detected",
            extra={"event": "refresh_failed", "error_type": "REFRESH_TOKEN_REUSE_DETECTED"},
        )
        response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "REFRESH_TOKEN_REUSE_DETECTED"},
        )

    if row is None:
        logger.warning(
            "refresh denied — invalid or expired refresh token",
            extra={"event": "refresh_failed", "error_type": "INVALID_OR_EXPIRED_REFRESH_TOKEN"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "INVALID_OR_EXPIRED_REFRESH_TOKEN"},
        )

    user = get_user_by_id(row["user_id"])
    if user is None:
        logger.error(
            f"refresh token valid but user_id={row['user_id']} not found",
            extra={"event": "refresh_failed", "error_type": "USER_NOT_FOUND"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "USER_NOT_FOUND"},
        )

    # Rotate: kill old, issue new
    revoke_refresh_token(old_token)
    new_refresh_token = generate_refresh_token()
    store_refresh_token(user["eid"], new_refresh_token)
    _set_refresh_cookie(response, new_refresh_token)

    role   = user["role"]
    scopes = _scopes_for_role(role)
    new_access_token = generate_user_token(
        user["eid"], scopes, expires_in_minutes=USER_TOKEN_MINUTES,
        role=role, store_id=user.get("store_id"),
    )

    return LoginResponse(
        token=new_access_token,
        expires_in=USER_TOKEN_MINUTES * 60,
        user=UserPublic(id=user["eid"], role=role, scopes=scopes),
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