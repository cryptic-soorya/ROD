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

import contextvars
import os
import sys
from dataclasses import dataclass

import jwt

from logging_config import get_logger

logger = get_logger("mcp.auth_middleware")

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
        logger.error(
            f"{JWT_SECRET_ENV_VAR} is not set — cannot verify signing secret",
            extra={"event": "startup_misconfigured", "error_type": "MissingSigningSecret"},
        )
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
        logger.error(
            "startup token is missing or empty",
            extra={"event": "startup_check_failed", "error_type": "MissingToken"},
        )
        sys.exit("auth_middleware: startup token is missing or empty.")

    secret = _get_signing_secret()

    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.error(
            "startup token has expired",
            extra={"event": "startup_check_failed", "error_type": "ExpiredSignatureError"},
        )
        sys.exit("auth_middleware: startup token has expired.")
    except jwt.InvalidTokenError as e:
        # Covers malformed tokens, bad signature, wrong algorithm, etc.
        # PyJWT's exception message doesn't include the token itself, so
        # this is safe to surface directly.
        logger.error(
            f"startup token is invalid ({type(e).__name__})",
            extra={"event": "startup_check_failed", "error_type": type(e).__name__},
        )
        sys.exit(f"auth_middleware: startup token is invalid ({type(e).__name__}).")

    global _token_payload
    _token_payload = payload
    logger.info(
        "startup token validated — MCP tool scope checks are now active",
        extra={"event": "startup_check_ok"},
    )


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
        logger.warning(
            f"scope check denied — no token payload (tool={tool_name})",
            extra={"event": "scope_denied", "error_type": "UNAUTHENTICATED"},
        )
        return {
            "error": "UNAUTHENTICATED",
            "message": "No valid token payload available. The server may not "
                        "have completed startup_check, or the token was rejected.",
            "tool": tool_name,
        }

    if required_scope not in _extract_scopes(token_payload):
        logger.warning(
            f"scope check denied — missing '{required_scope}' (tool={tool_name})",
            extra={"event": "scope_denied", "error_type": "MISSING_SCOPE"},
        )
        return {
            "error": "MISSING_SCOPE",
            "message": f"Token does not grant required scope '{required_scope}'.",
            "tool": tool_name,
        }

    return None


# ── Per-investigation store/role context (RBAC: manager scoped to own store) ─
#
# check_scope() above answers "is this system allowed to call this tool at
# all" — that's the single, static, process-lifetime agent service token.
# It has no idea which human (if any) triggered a given investigation, and
# it never will: agent tokens only carry sub + scopes (see jwt_handler.py's
# generate_agent_token()).
#
# "Which store is THIS investigation allowed to touch" is a different,
# per-request question that depends on the human manager who called
# investigations/router.py's create_investigation(). That identity has to
# travel with the investigation, not live on the process-wide token.
#
# We use a contextvars.ContextVar rather than a second module global because
# BackgroundTasks can run multiple investigations concurrently in this same
# process (e.g. a STORE-001 manager's and a STORE-002 manager's runs
# overlapping) — a plain global would let one investigation's store leak
# into another's tool calls mid-flight. asyncio.to_thread() (used by
# agent/orchestrator.py to run the graph) copies the *current* contextvars
# Context into its worker thread, so setting this once per investigation,
# before that call, is sufficient and stays isolated per investigation.


@dataclass(frozen=True)
class CallerContext:
    role: str                 # "admin" | "manager"
    store_id: str | None      # the manager's own store; None/ignored for admin


_caller_context: "contextvars.ContextVar[CallerContext | None]" = contextvars.ContextVar(
    "caller_context", default=None
)


def set_caller_context(role: str, store_id: str | None) -> None:
    """
    Called once per investigation — agent/orchestrator.run(), before the
    LangGraph run starts — with role/store_id read off the *human* caller's
    own verified JWT at investigation-creation time (investigations/router.py,
    same "never trust the request body" pattern already used there for eid).
    Never call this with a value derived from an LLM-suppliable tool argument.
    """
    _caller_context.set(CallerContext(role=role, store_id=store_id))


def get_caller_context() -> "CallerContext | None":
    return _caller_context.get()


def require_store_access(requested_store_id: str | None, tool_name: str | None = None) -> dict | None:
    """
    Strict check for tools where store_id is a REQUIRED argument (e.g.
    get_sales_data, get_inventory_levels). Call AFTER check_scope() passes.

    Admins pass through unrestricted. Managers may only query their own
    store — the permitted value comes from the CallerContext set at
    investigation-creation time from their own verified JWT, never from the
    store_id argument itself (that argument is chosen by the LLM agent and
    is not trustworthy as an authorization boundary on its own).

    Returns None if allowed, or a structured error dict if not. Fails closed
    (denies) if no caller context is present at all, rather than silently
    allowing unrestricted access outside the normal investigation flow.
    """
    caller = get_caller_context()

    if caller is None:
        logger.warning(
            f"store scope denied — no caller context (tool={tool_name})",
            extra={"event": "store_scope_denied", "error_type": "NO_CALLER_CONTEXT"},
        )
        return {
            "error": "NO_CALLER_CONTEXT",
            "message": "No caller store/role context is available for this investigation.",
            "tool": tool_name,
        }

    if caller.role == "admin":
        return None

    if requested_store_id != caller.store_id:
        logger.warning(
            f"store scope denied — manager scoped to '{caller.store_id}' "
            f"requested '{requested_store_id}' (tool={tool_name})",
            extra={"event": "store_scope_denied", "error_type": "STORE_FORBIDDEN"},
        )
        return {
            "error": "STORE_FORBIDDEN",
            "message": f"This token is scoped to store '{caller.store_id}' and cannot access store '{requested_store_id}'.",
            "tool": tool_name,
        }

    return None


def resolve_scoped_store_id(
    requested_store_id: str | None, tool_name: str | None = None
) -> tuple[str | None, dict | None]:
    """
    For tools where store_id is OPTIONAL (e.g. get_customer_complaints,
    get_return_reasons post-change). Returns (resolved_store_id, error).

    - Admin: passed through unchanged (None means "no filter", i.e. every
      store) — admins are allowed the unscoped view.
    - Manager, store_id given: must match their own store, else FORBIDDEN.
    - Manager, store_id omitted: force-scoped to their own store rather than
      silently returning every store's data — omission must never widen
      access.

    On error, resolved_store_id is None and the error dict should be
    returned by the caller as-is.
    """
    caller = get_caller_context()

    if caller is None:
        logger.warning(
            f"store scope denied — no caller context (tool={tool_name})",
            extra={"event": "store_scope_denied", "error_type": "NO_CALLER_CONTEXT"},
        )
        return None, {
            "error": "NO_CALLER_CONTEXT",
            "message": "No caller store/role context is available for this investigation.",
            "tool": tool_name,
        }

    if caller.role == "admin":
        return requested_store_id, None

    if requested_store_id is not None and requested_store_id != caller.store_id:
        logger.warning(
            f"store scope denied — manager scoped to '{caller.store_id}' "
            f"requested '{requested_store_id}' (tool={tool_name})",
            extra={"event": "store_scope_denied", "error_type": "STORE_FORBIDDEN"},
        )
        return None, {
            "error": "STORE_FORBIDDEN",
            "message": f"This token is scoped to store '{caller.store_id}' and cannot access store '{requested_store_id}'.",
            "tool": tool_name,
        }

    return caller.store_id, None


def filter_store_ids_for_caller(store_ids: list[str], tool_name: str | None = None) -> list[str]:
    """
    For tools that scan across ALL stores with no store_id argument at all
    (get_stores_with_sales_decline, get_stores_with_sku_decline). Given the
    candidate store_ids the query would otherwise consider, returns the
    subset the caller is allowed to see.

    Admins (or no caller context — see note below) get the list unchanged.
    Managers get it intersected down to just their own store.

    Note: unlike require_store_access/resolve_scoped_store_id, this does NOT
    fail closed on missing caller context, because these scan tools are also
    reachable from mcp_server/server.py's standalone stdio path where no
    per-investigation context is ever set. Failing closed there would make
    the tools unusable outside the agent flow. The strict, fail-closed checks
    above are used for anything that names a specific store, which is the
    actual point where cross-store data could leak.
    """
    caller = get_caller_context()
    if caller is None or caller.role == "admin":
        return store_ids
    return [s for s in store_ids if s == caller.store_id]