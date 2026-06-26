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
