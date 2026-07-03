"""
mcp_server/auth_middleware.py
OWNER: Team Lead

Two-layer JWT validation (SRS Section 3.1):
    Layer 1 — startup_check(token: str) -> None
        Called ONCE when MCP server starts.
        Raises SystemExit if token is missing, expired, or malformed.
        Decodes and caches the token's payload on success (this server runs
        with a single long-lived service token for its whole lifetime, not
        per-request tokens — see check_scope below).

    Layer 2 — check_scope(token_payload: dict, required_scope: str) -> dict | None
        Called at the TOP of EVERY tool function, before any DB connection opens.
        Returns a structured error dict ({"error", "message", "tool"}, matching
        the convention used by mcp_server/tools/*.py) if the scope is missing.
        Returns None if the scope check passes. Does NOT raise — a tool
        function must explicitly check the return value:

            def get_sales_data(store_id, period="last_30_days"):
                err = check_scope(get_token_payload(), "read:sales", tool_name="get_sales_data")
                if err:
                    return err
                ...

Key constraint: JWT / MCP_AUTH_TOKEN must NEVER appear in this file or in any
message to the LLM. This file only ever handles the token as an opaque
string passed in by the process environment / caller — it is never logged,
never included in an error message, and never returned to a caller.
"""

import os
import sys

import jwt

# ── Configuration ────────────────────────────────────────────────────────────
# The signing secret is separate from the token itself: MCP_AUTH_TOKEN (read
# by whoever calls startup_check) is the bearer token issued to this server;
# MCP_JWT_SECRET is the HMAC key used to verify that token's signature. They
# must never be the same value or come from the same source.
JWT_SECRET_ENV_VAR = "MCP_JWT_SECRET"
JWT_ALGORITHM = "HS256"  # explicit allow-list passed to jwt.decode — never accepts alg=none

# Cached payload from the single startup_check() call. Tool functions read
# this via get_token_payload() rather than re-decoding the token on every
# call, since there is exactly one service token for the process lifetime.
_token_payload: dict | None = None


def _get_signing_secret() -> str:
    secret = os.environ.get(JWT_SECRET_ENV_VAR)
    if not secret:
        # Fatal misconfiguration, not a token problem — still a startup-time
        # SystemExit since the server cannot verify anything without it.
        sys.exit(
            f"auth_middleware: {JWT_SECRET_ENV_VAR} is not set. "
            "Cannot verify the JWT signing secret at startup."
        )
    return secret


def startup_check(token: str) -> None:
    """
    Validates the server's service token once at startup. Raises SystemExit
    (not an exception the caller is expected to catch) if the token is
    missing, malformed, expired, or fails signature verification — an MCP
    server should not come up with an invalid credential.

    On success, caches the decoded payload for later use by check_scope via
    get_token_payload(). Never logs or echoes the raw token.
    """
    if not token or not token.strip():
        sys.exit("auth_middleware: startup token is missing or empty.")

    secret = _get_signing_secret()

    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        sys.exit("auth_middleware: startup token has expired.")
    except jwt.InvalidTokenError as e:
        # Covers malformed tokens, bad signature, wrong algorithm, etc.
        # PyJWT's exception message doesn't include the token itself, so
        # this is safe to surface directly.
        sys.exit(f"auth_middleware: startup token is invalid ({type(e).__name__}).")

    global _token_payload
    _token_payload = payload


def get_token_payload() -> dict | None:
    """
    Returns the payload cached by startup_check(), or None if startup_check
    has not been called (or the server hasn't finished starting yet). Tool
    functions should treat None as "not authenticated" and let check_scope's
    defensive handling produce the appropriate error dict.
    """
    return _token_payload


def _extract_scopes(token_payload: dict) -> set[str]:
    """
    Scopes may be represented as a single space-delimited string under the
    standard OAuth2 "scope" claim, or as a list under "scopes". Support both
    rather than assuming one convention was used when the token was issued.
    """
    scopes: set[str] = set()

    raw_scope = token_payload.get("scope")
    if isinstance(raw_scope, str):
        scopes.update(raw_scope.split())

    raw_scopes = token_payload.get("scopes")
    if isinstance(raw_scopes, (list, tuple, set)):
        scopes.update(str(s) for s in raw_scopes)

    return scopes


def check_scope(
    token_payload: dict | None,
    required_scope: str,
    tool_name: str | None = None,
) -> dict | None:
    """
    Checks whether token_payload grants required_scope.

    Returns None if the check passes. Returns a structured error dict if it
    fails — matching the {"error", "message", "tool"} shape used throughout
    mcp_server/tools/*.py — so a tool function can do:

        err = check_scope(get_token_payload(), "read:sales", tool_name="get_sales_data")
        if err:
            return err

    tool_name is optional so this stays call-compatible with the documented
    check_scope(token_payload, required_scope) signature; pass it when
    available so the returned error dict's "tool" field is populated the
    same way every other tool error already is.
    """
    if not token_payload:
        return {
            "error": "UNAUTHENTICATED",
            "message": "No valid token payload available. The server may not "
                        "have completed startup_check, or the token was rejected.",
            "tool": tool_name,
        }

    if required_scope not in _extract_scopes(token_payload):
        return {
            "error": "MISSING_SCOPE",
            "message": f"Token does not grant required scope '{required_scope}'.",
            "tool": tool_name,
        }

    return None