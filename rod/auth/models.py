"""
auth/models.py
OWNER: Teammate A

Pydantic models for authentication.
"""

from pydantic import BaseModel
from typing import List


class UserPublic(BaseModel):
    """User info returned inside the login response (never exposes password)."""
    id: str
    role: str
    scopes: List[str]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in: int          # seconds
    token_type: str = "Bearer"
    user: UserPublic
