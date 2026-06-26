"""
investigations/service.py
OWNER: Teammate B

Business logic:
- queue_investigation()   → writes to orchestration.db, spawns agent asynchronously
- get_status()            → reads current iteration count + partial evidence trail
- list_investigations()   → paginated query, default sort created_at DESC
- update_status()         → called by agent after each ReAct iteration (must update within 1 second)

Status transitions: pending → in_progress → completed OR escalated
"""
