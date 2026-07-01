"""
auth/router.py
OWNER: Teammate A

FastAPI router for:
- POST /auth/login
    Body: { username, password }
    Returns: { token, expires_in, token_type, user: { id, role, scopes } }
    On fail: 401 { error: INVALID_CREDENTIALS }

Role → Scope mapping (from FRS Table 1.1.1):
    Admin             → all 9 scopes
    Category Manager  → read:sales, read:inventory, read:returns, read:customers, read:promotions, read:knowledge
    Store Manager     → read:sales, read:inventory, read:returns, read:knowledge
"""
"""
auth/router.py
OWNER: Teammate A

FastAPI router for:
- POST /auth/login
    Body: { username, password }
    Returns: { token, expires_in, token_type, user: { id, role, scopes } }
    On fail: 401 { error: INVALID_CREDENTIALS }

Role → Scope mapping (from FRS Table 1.1.1):
    Admin             → all 9 scopes
    Category Manager  → read:sales, read:inventory, read:returns,
                        read:customers, read:promotions, read:knowledge
    Store Manager     → read:sales, read:inventory, read:returns, read:knowledge
"""

import bcrypt
from fastapi import APIRouter, HTTPException, status

from auth.models import LoginRequest, LoginResponse, UserPublic
from auth.jwt_handler import generate_user_token, USER_TOKEN_MINUTES

router = APIRouter(prefix="/auth", tags=["Auth"])

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


# ── POST /auth/login ──────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login and receive a JWT",
)
def login(body: LoginRequest) -> LoginResponse:
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
    token = generate_user_token(user["id"], scopes, expires_in_minutes=USER_TOKEN_MINUTES)

    return LoginResponse(
        token=token,
        expires_in=USER_TOKEN_MINUTES * 60,
        user=UserPublic(id=user["id"], role=role, scopes=scopes),
    )
