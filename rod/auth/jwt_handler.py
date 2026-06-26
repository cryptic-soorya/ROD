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
