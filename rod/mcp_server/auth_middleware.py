"""
mcp_server/auth_middleware.py
OWNER: Team Lead

Two-layer JWT validation (SRS Section 3.1):
    Layer 1 — startup_check(token: str) -> None
        Called ONCE when MCP server starts.
        Raises SystemExit if token is missing, expired, or malformed.

    Layer 2 — check_scope(token_payload: dict, required_scope: str) -> None
        Called at the TOP of EVERY tool function, before any DB connection opens.
        Returns structured error dict if scope missing — does not crash the investigation.
"""
