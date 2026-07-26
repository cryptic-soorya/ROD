"""
investigations/service.py
OWNER: Teammate B

Business logic:
- queue_investigation()   → writes to Postgres (orchestration schema), spawns agent asynchronously
- get_status()            → reads current status + partial evidence trail (tool_calls) + latest report
- list_investigations()   → paginated query, default sort investigation_id DESC
- update_status()         → called by agent after each ReAct iteration; writes status + (optionally) a new report row

Status transitions: pending → in_progress → completed OR escalated

DB: PostgreSQL, schema `orchestration` (tables investigations, tool_calls,
audit_logs, reports, ...). Tables are assumed to already exist -- this module
does not create them.

SCHEMA NOTE (2026-07-20): `investigations` no longer carries id/created_at/
updated_at/completed_at/iteration_count/report. PK is `investigation_id`
(identity column) and reports now live in their own `reports` table
(one row per version, per investigation). iteration_count is gone entirely.

POOL NOTE: connections now come from the shared pool in db_pool.py (started
once at app startup in main.py) instead of opening a fresh connection per
call. Every conn = get_conn(DB_DSN) must be matched with put_conn(DB_DSN, conn)
in a finally block — never conn.close().
"""

import os
import json
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
        query=row["query"],
        status=InvestigationStatus(row["status"]),
        priority=row["priority"],
        store_id=row["store_id"],
        sku=row["sku_id"],
    )


def _audit(conn, investigation_id: int, event: str, detail: str = "") -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO orchestration.audit_logs (investigation_id, event, detail) "
            "VALUES (%s, %s, %s)",
            (investigation_id, event, detail),
        )


# ── Public service functions ───────────────────────────────────────────────────

def queue_investigation(payload: InvestigationCreate) -> InvestigationResponse:
    """
    Writes a new investigation to Postgres with status=pending.
    Denormalises store_id and sku_id from context for efficient list filtering.
    The agent is spawned by the router's BackgroundTask — not here.
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
                       (query, context, priority, store_id, sku_id, status)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING investigation_id""",
                    (
                        payload.query,
                        json.dumps(context) if context else None,
                        payload.priority,
                        store_id,
                        sku_id,
                        InvestigationStatus.PENDING.value,
                    ),
                )
                inv_id = cur.fetchone()["investigation_id"]
                _audit(conn, inv_id, "created", f"priority={payload.priority}")

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
    caller_store_id: Optional[str] = None,   # set for store_manager role enforcement
) -> PaginatedInvestigations:
    """
    Paginated list, default sort: investigation_id DESC (investigations has
    no created_at anymore, so identity order stands in for recency).
    Store Manager access control: if caller_store_id is set, results are silently
    restricted to that store (returns empty list rather than 403 for other stores).

    NOTE: date_from/date_to filtering was dropped — investigations has no
    timestamp column to filter on. If that's needed, it'll have to join
    against reports.generated_at or tool_calls.called_at instead.
    """
    clauses = []
    params  = []

    # Store Manager: restrict to their own store (no 403 leak — returns empty)
    if caller_store_id is not None:
        clauses.append("store_id = %s")
        params.append(caller_store_id)

    if status:
        clauses.append("status = %s")
        params.append(status.value)

    if store_id:
        # If store manager tries to filter another store's id, this will yield 0 rows
        clauses.append("store_id = %s")
        params.append(store_id)

    if sku:
        clauses.append("sku_id = %s")
        params.append(sku)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = get_conn(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM orchestration.investigations {where}", params)
            total = cur.fetchone()["total"]

        offset = (page - 1) * per_page
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT * FROM orchestration.investigations {where}
                    ORDER BY investigation_id DESC
                    LIMIT %s OFFSET %s""",
                [*params, per_page, offset],
            )
            rows = cur.fetchall()
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

    Status just gets written straight through — no more updated_at/
    completed_at/iteration_count columns on investigations to touch.

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

            if affected:
                _audit(conn, investigation_id, "status_changed", new_status.value)
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