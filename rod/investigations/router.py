"""
investigations/router.py
OWNER: Teammate B

FastAPI router for:
- POST   /api/v1/detective/investigate          → queue investigation, return 202 + InvestigationId
- GET    /api/v1/detective/investigation/{id}   → status + partial evidence trail
- GET    /api/v1/detective/investigations       → paginated history (filters: store_id, sku, status)

Access control:
- Manager sees only investigations they personally started (eid-scoped).
- Admin sees every investigation.
- Querying investigation IDs that aren't theirs returns empty list, NOT 403
  (avoid leaking existence — SRS Section 2.3).

SCHEMA NOTE (2026-07-20): `investigations` dropped id/created_at/updated_at/
completed_at/iteration_count. PK is now `investigation_id`, and
date_from/date_to filtering was dropped from list_investigations since
there's no timestamp column left on `investigations` to filter on.

SCHEMA NOTE (2026-07-26): `investigations.eid` added (FK -> rod_auth.user.eid).
create_investigation() now passes the caller's own eid — read from their
verified JWT's "sub" claim (token_payload["sub"], set at login time in
auth/jwt_handler.py's _encode()) — into service.queue_investigation(). This
is deliberately NOT taken from the request body: a user must never be able
to submit an investigation attributed to a different eid than their own.
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
        from agent.orchestrator import run as run_investigation  # lazy import avoids circular deps
        service.update_status(investigation_id, InvestigationStatus.IN_PROGRESS)
        await run_investigation(investigation_id, query, context)
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

    eid is taken from the caller's own verified JWT ("sub" claim) — never
    from the request body — so the investigation is always attributed to
    whoever is actually authenticated, not a client-supplied value.
    """
    eid = token_payload.get("sub")
    investigation = service.queue_investigation(payload, eid=eid)
    background_tasks.add_task(
        _run_agent,
        investigation.investigation_id,
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
    Returns the full investigation record, the latest report (if any), and
    all tool calls logged so far (the partial evidence trail while in progress).
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
    token_payload: dict = Depends(require_auth),
):
    """
    Returns paginated investigation history sorted by investigation_id DESC
    (investigations has no created_at anymore).

    Manager access control: a manager only sees investigations they
    personally started — their JWT's "sub" claim (their own eid) is
    silently injected as a filter, regardless of what store_id/sku they
    pass in the query string. A manager with zero investigations of their
    own gets an empty list, never a 403.

    role/store_id are real top-level JWT claims (see auth/jwt_handler.py's
    generate_user_token) — category_manager and store_manager were collapsed
    into a single "manager" role (2026-07-27); admins are unrestricted.
    """
    # Enforce Manager restriction — scoped to investigations they started
    caller_eid: Optional[str] = None
    role = token_payload.get("role")
    if role == "manager":
        caller_eid = token_payload.get("sub")

    return service.list_investigations(
        page=page,
        per_page=per_page,
        status=status_,
        store_id=store_id,
        sku=sku,
        caller_eid=caller_eid,
    )


# ── PATCH /api/v1/detective/investigation/{id}/status (agent/internal) ────────

class _StatusUpdate(Report):
    """Body for the internal PATCH endpoint — adds required status field."""
    status: InvestigationStatus


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
    report = Report(**body.model_dump(exclude={"status"}))
    ok = service.update_status(
        investigation_id,
        body.status,
        report,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation {investigation_id} not found",
        )
    return service.get_status(investigation_id)