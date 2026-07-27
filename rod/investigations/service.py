"""
investigations/service.py

Business logic:
- queue_investigation()   → writes to Postgres (orchestration schema), spawns agent asynchronously
- get_status()            → reads current status + partial evidence trail (tool_calls) + latest report
- list_investigations()   → paginated query, default sort created_at DESC (investigation_id DESC tiebreak)
- update_status()         → called by agent after each ReAct iteration; writes status + (optionally) a new report row
- log_root_cause()        → persists a row to orchestration.root_causes

Status transitions: pending → in_progress → completed OR escalated

DB: PostgreSQL, schema `orchestration` (tables investigations, tool_calls,
audit_logs, reports, ...). Tables are assumed to already exist
-- this module does not create them.

SCHEMA NOTE (2026-07-26): investigations.created_at is back (see
add_investigations_created_at.sql) — DB-side default now(), so inserts don't
need to set it explicitly. list_investigations now sorts by it, with
investigation_id DESC as a tiebreak for same-timestamp rows.

SCHEMA NOTE (2026-07-27): list_investigations()'s manager restriction
changed from store_id-based to eid-based — a manager now only sees
investigations they personally started (investigations.eid = their own
eid), not every investigation tagged to their store. See
investigations/router.py's list_investigations() for where caller_eid is
set from the verified JWT.
"""

import os
import json
import uuid
from typing import Optional

import psycopg2
import psycopg2.extras

from investigations.models import (
    InvestigationCreate,
    InvestigationResponse,
    InvestigationListItem,
    InvestigationStatus,
    Report,
    ToolCall,
    PaginatedInvestigations,
)
from db_pool import get_conn, put_conn

DB_DSN = os.getenv("ORCHESTRATION_DB_URL", os.getenv("DATABASE_URL"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _maybe_json(value):
    """context/input_args/output/report_json may be stored as TEXT (json.dumps'd)
    or as native JSON/JSONB (already parsed by psycopg2). Handle both."""
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _maybe_dt(value):
    """generated_at/called_at/logged_at may be stored as TEXT (isoformat string)
    or as native TIMESTAMP (already a datetime from psycopg2). Handle both."""
    if value is None:
        return None
    if isinstance(value, str):
        from datetime import datetime
        return datetime.fromisoformat(value)
    return value


def _load_tool_calls(conn, investigation_id: int) -> list[ToolCall]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM orchestration.tool_calls WHERE investigation_id = %s ORDER BY id",
            (investigation_id,),
        )
        rows = cur.fetchall()
    return [
        ToolCall(
            id=r["id"],
            investigation_id=r["investigation_id"],
            tool_name=r["tool_name"],
            input_args=_maybe_json(r["input_args"]),
            output=_maybe_json(r["output"]) if r["output"] is not None else None,
            error=r["error"],
            called_at=_maybe_dt(r["called_at"]),
        )
        for r in rows
    ]


def _load_latest_report(conn, investigation_id: int) -> Optional[Report]:
    """
    reports has one row per version now; take the highest version.

    NOTE (2026-07-20): report_json now stores the FULL FRS report dict
    produced by reports.generator.compile_report / written by
    reports_service.save_report() (that module is the sole writer into
    orchestration.reports now — see update_status()'s docstring). Its shape
    doesn't line up field-for-field with investigations.models.Report:
    report_json already has its own "investigation_id"/"generated_at" keys
    (spreading it as **body used to collide with the explicit kwargs below),
    "evidence" is a list of {step,tool,finding} dicts rather than
    Report.evidence_trail's List[str], and "recommendations" is a
    {immediate/customer_recovery/process_improvement} dict rather than
    Report.recommendations' List[str]. This maps the compatible fields
    across and converts the two that aren't, instead of spreading.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT * FROM orchestration.reports
               WHERE investigation_id = %s
               ORDER BY version DESC
               LIMIT 1""",
            (investigation_id,),
        )
        row = cur.fetchone()
    if not row:
        return None

    body = _maybe_json(row["report_json"]) or {}

    evidence_trail = [
        f"Step {e.get('step')}: called {e.get('tool')} → {e.get('finding')}"
        for e in (body.get("evidence") or [])
    ]

    recs = body.get("recommendations")
    if isinstance(recs, dict):
        recommendations = [
            item
            for bucket in ("immediate", "customer_recovery", "process_improvement")
            for item in (recs.get(bucket) or [])
        ]
    elif isinstance(recs, list):
        recommendations = recs
    else:
        recommendations = []

    return Report(
        investigation_id=row["investigation_id"],
        version=row["version"],
        executive_summary=row["executive_summary"],
        generated_at=_maybe_dt(row["generated_at"]),
        anomaly_category=body.get("anomaly_category"),
        confidence_score=body.get("confidence_score"),
        root_cause=body.get("root_cause"),
        recommendations=recommendations,
        evidence_trail=evidence_trail,
        estimated_impact=body.get("estimated_impact"),
    )



def _row_to_response(row, tool_calls: list[ToolCall], report: Optional[Report]) -> InvestigationResponse:
    return InvestigationResponse(
        investigation_id=row["investigation_id"],
        eid=row["eid"],
        query=row["query"],
        context=_maybe_json(row["context"]) if row["context"] else None,
        priority=row["priority"],
        status=InvestigationStatus(row["status"]),
        report=report,
        tool_calls=tool_calls,
    )


def _row_to_list_item(row) -> InvestigationListItem:
    return InvestigationListItem(
        investigation_id=row["investigation_id"],
        eid=row["eid"],
        query=row["query"],
        status=InvestigationStatus(row["status"]),
        priority=row["priority"],
        store_id=row["store_id"],
        sku=row["sku_id"],
    )


# ── Public service functions ───────────────────────────────────────────────────

def queue_investigation(payload: InvestigationCreate, eid: Optional[str] = None) -> InvestigationResponse:
    """
    Writes a new investigation to Postgres with status=pending.
    Denormalises store_id and sku_id from context for efficient list filtering.
    created_at is left unset here — DB default now() fills it in.
    The agent is spawned by the router's BackgroundTask — not here.

    eid links the investigation to the rod_auth.user who requested it
    (orchestration.investigations.eid -> rod_auth.user.eid). The router
    passes the caller's own eid from their verified JWT (token_payload["sub"])
    — never a client-supplied value, so a user can't submit an investigation
    on someone else's behalf. Optional/nullable since some internal or
    system-triggered investigations may have no human requester.
    """
    context = payload.context or {}
    store_id = context.get("store_id")
    sku_id   = context.get("sku")

    conn = get_conn(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO orchestration.investigations
                       (eid, query, context, priority, store_id, sku_id, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       RETURNING investigation_id""",
                    (
                        eid,
                        payload.query,
                        json.dumps(context) if context else None,
                        payload.priority,
                        store_id,
                        sku_id,
                        InvestigationStatus.PENDING.value,
                    ),
                )
                inv_id = cur.fetchone()["investigation_id"]

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM orchestration.investigations WHERE investigation_id = %s",
                    (inv_id,),
                )
                row = cur.fetchone()

        return _row_to_response(row, [], None)
    finally:
        put_conn(DB_DSN, conn)


def get_status(investigation_id: int) -> Optional[InvestigationResponse]:
    """
    Returns the investigation record plus tool_calls logged so far (partial
    evidence trail) and the latest report, if any.
    Returns None if the investigation does not exist.
    """
    conn = get_conn(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM orchestration.investigations WHERE investigation_id = %s",
                (investigation_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        tool_calls = _load_tool_calls(conn, investigation_id)
        report = _load_latest_report(conn, investigation_id)
        return _row_to_response(row, tool_calls, report)
    finally:
        put_conn(DB_DSN, conn)


def list_investigations(
    page:       int = 1,
    per_page:   int = 20,
    status:     Optional[InvestigationStatus] = None,
    store_id:   Optional[str] = None,
    sku:        Optional[str] = None,
    caller_eid: Optional[str] = None,   # set for manager role enforcement — restricts to investigations they started
) -> PaginatedInvestigations:
    """
    Paginated list, sorted by created_at DESC (investigation_id DESC as a
    tiebreak for rows created in the same instant — created_at alone isn't
    guaranteed unique under concurrent inserts).

    Manager access control: if caller_eid is set, results are silently
    restricted to investigations that eid started (returns empty list for
    a manager with no investigations, rather than 403). Admins pass
    caller_eid=None and see everything.
    """
    clauses = []
    params  = []

    # Manager: restrict to investigations they personally started (no 403
    # leak — an empty list, same pattern as the old store_id restriction).
    if caller_eid is not None:
        clauses.append("eid = %s")
        params.append(caller_eid)

    if status:
        clauses.append("status = %s")
        params.append(status.value)

    if store_id:
        clauses.append("store_id = %s")
        params.append(store_id)

    if sku:
        clauses.append("sku_id = %s")
        params.append(sku)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    # Single round trip instead of a separate COUNT(*) query first:
    # COUNT(*) OVER() returns the full matching-row total on every row of
    # the same result set. Worth doing specifically because this DB is a
    # Supabase instance in ap-southeast-2 — every extra round trip from
    # India is a real, user-visible chunk of this endpoint's load time.
    offset = (page - 1) * per_page
    conn = get_conn(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT *, COUNT(*) OVER() AS _total
                    FROM orchestration.investigations {where}
                    ORDER BY created_at DESC, investigation_id DESC
                    LIMIT %s OFFSET %s""",
                [*params, per_page, offset],
            )
            rows = cur.fetchall()

        # COUNT(*) OVER() only appears on rows actually returned, so an
        # empty page (e.g. page 5 of a 2-page result, or genuinely zero
        # matches) needs its own count — this is the rare path, not the
        # common one, so it doesn't undo the round-trip savings above.
        if rows:
            total = rows[0]["_total"]
        elif offset == 0:
            total = 0
        else:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) AS total FROM orchestration.investigations {where}",
                    params,
                )
                total = cur.fetchone()["total"]
    finally:
        put_conn(DB_DSN, conn)

    return PaginatedInvestigations(
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, -(-total // per_page)),
        items=[_row_to_list_item(r) for r in rows],
    )


def update_status(
    investigation_id: int,
    new_status: InvestigationStatus,
    report: Optional[Report] = None,
) -> bool:
    """
    Called by the ReAct agent after each iteration and at end_turn.
    Must complete within 1 second (SRS constraint).
    Returns True if the row was found and updated, False otherwise.

    NOTE (2026-07-20): `report` is accepted for backward-compat call sites
    but is NOT persisted here anymore. It used to insert into
    orchestration.reports directly, but reports_service.save_report()
    (reports/service.py) already inserts a version row for every code path
    that calls update_status() with a report — having both write into the
    same versioned table meant GET /report/{id} nondeterministically
    returned whichever one wrote last, and their shapes don't match (this
    module's Report is the narrower business shape; reports_service's is
    the full FRS report the frontend actually reads). reports_service is
    now the single writer for orchestration.reports.
    """
    conn = get_conn(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE orchestration.investigations
                       SET status = %s
                       WHERE investigation_id = %s""",
                    (new_status.value, investigation_id),
                )
                affected = cur.rowcount
        return affected > 0
    finally:
        put_conn(DB_DSN, conn)


def log_tool_call(
    investigation_id: int,
    tool_name: str,
    input_args: dict,
    output=None,
    error: Optional[str] = None,
) -> int:
    """
    Persists a single tool call record. Called by the ReAct loop after each
    Action → Observation step to build the evidence trail.
    Returns the new tool_call id.
    """
    conn = get_conn(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO orchestration.tool_calls
                       (investigation_id, tool_name, input_args, output, error)
                       VALUES (%s, %s, %s, %s, %s)
                       RETURNING id""",
                    (
                        investigation_id,
                        tool_name,
                        json.dumps(input_args),
                        json.dumps(output, default=str) if output is not None else None,
                        error,
                    ),
                )
                tc_id = cur.fetchone()["id"]
        return tc_id
    finally:
        put_conn(DB_DSN, conn)


def log_root_cause(
    investigation_id: int,
    cause_category: Optional[str] = None,
    cause_description: Optional[str] = None,
    confidence: Optional[float] = None,
) -> str:
    """
    Persists a row to orchestration.root_causes. Called by the ReAct agent
    when it identifies a candidate root cause during an investigation —
    an investigation can have several of these (one per hypothesis explored),
    unlike reports which is one-row-per-final-version.

    id is generated here (uuid4 hex) since that column is a text PK with no
    identity/serial default — same pattern reports/service.py's report_id use.
    Returns the new root_cause id.
    """
    cause_id = uuid.uuid4().hex

    conn = get_conn(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO orchestration.root_causes
                       (id, investigation_id, cause_category, cause_description, confidence)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (
                        cause_id,
                        investigation_id,
                        cause_category,
                        cause_description,
                        confidence,
                    ),
                )
        return cause_id
    finally:
        put_conn(DB_DSN, conn)

