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
"""
investigations/router.py
OWNER: Teammate B

FastAPI router for:
- POST   /api/v1/detective/investigate          → queue investigation, return 202 + InvestigationId
- GET    /api/v1/detective/investigation/{id}   → status + partial evidence trail
- GET    /api/v1/detective/investigations       → paginated history
                                                  (filters: store_id, sku, date_range, status)

Access control:
- Store Manager sees only their own store's investigations.
- Querying another store's store_id returns empty list, NOT 403
  (avoid leaking store existence — SRS Section 2.3).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from typing import Optional

from auth.jwt_handler import verify_token, check_scope
from investigations.models import (
    InvestigationCreate,
    InvestigationResponse,
    InvestigationStatus,
    PaginatedInvestigations,
    Report,
)
from investigations import service
from logging_config import get_logger

logger = get_logger("investigations.router")

router = APIRouter(
    prefix="/api/v1/detective",
    tags=["Investigations"],
)


# ── Auth dependency ────────────────────────────────────────────────────────────

def require_auth(payload: dict = Depends(verify_token)) -> dict:
    """Returns the decoded JWT payload. HTTPException raised by verify_token on failure."""
    return payload


# ── Background: run the ReAct agent ───────────────────────────────────────────

async def _run_agent(investigation_id: int, query: str, context: Optional[dict]) -> None:
    """
    BackgroundTask: transitions the investigation to in_progress, then hands off
    to the ReAct loop. On any crash the investigation is marked escalated so it
    is never left in in_progress forever.
    """
    try:
        from agent.react_loop import run as react_run  # lazy import avoids circular deps
        service.update_status(investigation_id, InvestigationStatus.IN_PROGRESS)
        await react_run(investigation_id, query, context)
    except Exception as exc:
        logger.error(
            f"investigation {investigation_id} crashed in the agent background task",
            extra={
                "event": "agent_crash",
                "investigation_id": str(investigation_id),
                "error_type": type(exc).__name__,
            },
            exc_info=True,
        )
        service.update_status(
            investigation_id,
            InvestigationStatus.ESCALATED,
            Report(root_cause=f"Agent error: {exc}", evidence_trail=[str(exc)]),
        )


# ── POST /api/v1/detective/investigate ────────────────────────────────────────

@router.post(
    "/investigate",
    response_model=InvestigationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a new investigation",
)
async def create_investigation(
    payload: InvestigationCreate,
    background_tasks: BackgroundTasks,
    token_payload: dict = Depends(require_auth),
):
    """
    Accepts an investigation query and optional context (store_id, sku, etc.).
    Returns 202 immediately with status=pending.
    The ReAct agent loop runs asynchronously via BackgroundTasks.
    """
    investigation = service.queue_investigation(payload)
    background_tasks.add_task(
        _run_agent,
        investigation.id,
        payload.query,
        payload.context,
    )
    return investigation


# ── GET /api/v1/detective/investigation/{id} ──────────────────────────────────

@router.get(
    "/investigation/{investigation_id}",
    response_model=InvestigationResponse,
    summary="Get investigation status and partial evidence trail",
)
def get_investigation(
    investigation_id: int,
    token_payload: dict = Depends(require_auth),
):
    """
    Returns the full investigation record including iteration_count and all
    tool calls logged so far (the partial evidence trail while in progress).
    """
    inv = service.get_status(investigation_id)
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation {investigation_id} not found",
        )
    return inv


# ── GET /api/v1/detective/investigations ──────────────────────────────────────

@router.get(
    "/investigations",
    response_model=PaginatedInvestigations,
    summary="Paginated investigation history with filters",
)
def list_investigations(
    page:      int = Query(1, ge=1),
    per_page:  int = Query(20, ge=1, le=100),
    status_:   Optional[InvestigationStatus] = Query(None, alias="status",
                    description="Filter by status"),
    store_id:  Optional[str] = Query(None, description="Filter by store_id"),
    sku:       Optional[str] = Query(None, description="Filter by SKU"),
    date_from: Optional[str] = Query(None, description="ISO date e.g. 2024-01-01"),
    date_to:   Optional[str] = Query(None, description="ISO date e.g. 2024-12-31"),
    token_payload: dict = Depends(require_auth),
):
    """
    Returns paginated investigation history sorted by created_at DESC.

    Store Manager access control: their JWT's store_id is silently injected as a
    filter — they can only see their own store's investigations regardless of what
    store_id they pass in the query string. A different store_id returns an empty
    list, never a 403.
    """
    # Enforce Store Manager restriction
    caller_store_id: Optional[str] = None
    role = token_payload.get("role")
    if role == "store_manager":
        # store_id is embedded in the token (set at login time)
        caller_store_id = token_payload.get("store_id")

    return service.list_investigations(
        page=page,
        per_page=per_page,
        status=status_,
        store_id=store_id,
        sku=sku,
        date_from=date_from,
        date_to=date_to,
        caller_store_id=caller_store_id,
    )


# ── PATCH /api/v1/detective/investigation/{id}/status (agent/internal) ────────

class _StatusUpdate(Report):
    """Body for the internal PATCH endpoint — adds required status field."""
    status: InvestigationStatus
    increment_iteration: bool = False


@router.patch(
    "/investigation/{investigation_id}/status",
    response_model=InvestigationResponse,
    summary="Update investigation status (agent / internal use only)",
    include_in_schema=False,   # hidden from public docs
)
def update_status(
    investigation_id: int,
    body: _StatusUpdate,
    token_payload: dict = Depends(require_auth),
):
    report = Report(**body.model_dump(exclude={"status", "increment_iteration"}))
    ok = service.update_status(
        investigation_id,
        body.status,
        report,
        increment_iteration=body.increment_iteration,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation {investigation_id} not found",
        )
    return service.get_status(investigation_id)
