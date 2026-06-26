"""
investigations/router.py
OWNER: Teammate B

FastAPI router for:
- POST   /api/v1/detective/investigate          → queue investigation, return 202 + InvestigationId
- GET    /api/v1/detective/investigation/{id}  → status + partial evidence trail
- GET    /api/v1/detective/investigations      → paginated history (filters: store_id, sku, date_range, status)

Access control:
- Store Manager sees only their own store's investigations.
- Querying another store's store_id returns empty list, NOT 403 (avoid leaking store existence).
"""
