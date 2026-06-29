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
"""
investigations/service.py
OWNER: Teammate B

Business logic:
- queue_investigation()   → writes to orchestration.db, spawns agent asynchronously
- get_status()            → reads current iteration count + partial evidence trail
- list_investigations()   → paginated query, default sort created_at DESC
- update_status()         → called by agent after each ReAct iteration
                            (must update within 1 second)

Status transitions: pending → in_progress → completed OR escalated
"""

import sqlite3
import json
import math
import pathlib
from datetime import datetime
from typing import Optional

from investigations.models import (
    InvestigationCreate,
    InvestigationResponse,
    InvestigationListItem,
    InvestigationStatus,
    Report,
    ToolCall,
    PaginatedInvestigations,
)

# DB lives inside the investigations/ package folder
DB_PATH = str(pathlib.Path(__file__).parent / "orchestration.db")


# ── DB connection ──────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ── Schema bootstrap ──────────────────────────────────────────────────────────

def init_db() -> None:
    """Creates all tables and indexes. Safe to call multiple times (IF NOT EXISTS)."""
    conn = get_db()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS investigations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                query           TEXT    NOT NULL,
                context         TEXT,                   -- JSON blob
                priority        INTEGER NOT NULL DEFAULT 1,
                store_id        TEXT,                   -- denormalised from context for fast filtering
                sku             TEXT,                   -- denormalised from context for fast filtering
                status          TEXT    NOT NULL DEFAULT 'pending',
                iteration_count INTEGER NOT NULL DEFAULT 0,
                report          TEXT,                   -- JSON blob (Report)
                created_at      TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL,
                completed_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                investigation_id INTEGER NOT NULL REFERENCES investigations(id),
                tool_name        TEXT    NOT NULL,
                input_args       TEXT    NOT NULL,      -- JSON
                output           TEXT,                  -- JSON
                error            TEXT,
                called_at        TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                investigation_id INTEGER REFERENCES investigations(id),
                event            TEXT    NOT NULL,
                detail           TEXT,
                logged_at        TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_inv_status   ON investigations(status);
            CREATE INDEX IF NOT EXISTS idx_inv_store    ON investigations(store_id);
            CREATE INDEX IF NOT EXISTS idx_inv_sku      ON investigations(sku);
            CREATE INDEX IF NOT EXISTS idx_inv_created  ON investigations(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tc_inv       ON tool_calls(investigation_id);
        """)
    conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat()


def _load_tool_calls(conn: sqlite3.Connection, investigation_id: int) -> list[ToolCall]:
    rows = conn.execute(
        "SELECT * FROM tool_calls WHERE investigation_id = ? ORDER BY id",
        (investigation_id,),
    ).fetchall()
    return [
        ToolCall(
            id=r["id"],
            investigation_id=r["investigation_id"],
            tool_name=r["tool_name"],
            input_args=json.loads(r["input_args"]),
            output=json.loads(r["output"]) if r["output"] else None,
            error=r["error"],
            called_at=datetime.fromisoformat(r["called_at"]),
        )
        for r in rows
    ]


def _row_to_response(row: sqlite3.Row, tool_calls: list[ToolCall]) -> InvestigationResponse:
    report_obj = Report(**json.loads(row["report"])) if row["report"] else None
    return InvestigationResponse(
        id=row["id"],
        query=row["query"],
        context=json.loads(row["context"]) if row["context"] else None,
        priority=row["priority"],
        status=InvestigationStatus(row["status"]),
        iteration_count=row["iteration_count"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        report=report_obj,
        tool_calls=tool_calls,
    )


def _row_to_list_item(row: sqlite3.Row) -> InvestigationListItem:
    report = json.loads(row["report"]) if row["report"] else {}
    return InvestigationListItem(
        id=row["id"],
        query=row["query"],
        status=InvestigationStatus(row["status"]),
        priority=row["priority"],
        store_id=row["store_id"],
        sku=row["sku"],
        created_at=datetime.fromisoformat(row["created_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        confidence_score=report.get("confidence_score"),
    )


def _audit(conn: sqlite3.Connection, investigation_id: int, event: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_logs (investigation_id, event, detail, logged_at) VALUES (?, ?, ?, ?)",
        (investigation_id, event, detail, _now()),
    )


# ── Public service functions ───────────────────────────────────────────────────

def queue_investigation(payload: InvestigationCreate) -> InvestigationResponse:
    """
    Writes a new investigation to orchestration.db with status=pending.
    Denormalises store_id and sku from context for efficient list filtering.
    The agent is spawned by the router's BackgroundTask — not here.
    """
    now = _now()
    context = payload.context or {}
    store_id = context.get("store_id")
    sku      = context.get("sku")

    conn = get_db()
    with conn:
        cur = conn.execute(
            """INSERT INTO investigations
               (query, context, priority, store_id, sku, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.query,
                json.dumps(context) if context else None,
                payload.priority,
                store_id,
                sku,
                InvestigationStatus.PENDING.value,
                now,
                now,
            ),
        )
        inv_id = cur.lastrowid
        _audit(conn, inv_id, "created", f"priority={payload.priority}")

    row = conn.execute("SELECT * FROM investigations WHERE id = ?", (inv_id,)).fetchone()
    conn.close()
    return _row_to_response(row, [])


def get_status(investigation_id: int) -> Optional[InvestigationResponse]:
    """
    Returns the full investigation record including the current iteration count
    and any tool calls logged so far (partial evidence trail).
    Returns None if the investigation does not exist.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM investigations WHERE id = ?", (investigation_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    tool_calls = _load_tool_calls(conn, investigation_id)
    conn.close()
    return _row_to_response(row, tool_calls)


def list_investigations(
    page:       int = 1,
    per_page:   int = 20,
    status:     Optional[InvestigationStatus] = None,
    store_id:   Optional[str] = None,
    sku:        Optional[str] = None,
    date_from:  Optional[str] = None,   # ISO date string e.g. "2024-01-01"
    date_to:    Optional[str] = None,
    caller_store_id: Optional[str] = None,   # set for store_manager role enforcement
) -> PaginatedInvestigations:
    """
    Paginated list, default sort: created_at DESC.
    Store Manager access control: if caller_store_id is set, results are silently
    restricted to that store (returns empty list rather than 403 for other stores).
    """
    clauses = []
    params  = []

    # Store Manager: restrict to their own store (no 403 leak — returns empty)
    if caller_store_id is not None:
        clauses.append("store_id = ?")
        params.append(caller_store_id)

    if status:
        clauses.append("status = ?")
        params.append(status.value)

    if store_id:
        # If store manager tries to filter another store's id, this will yield 0 rows
        clauses.append("store_id = ?")
        params.append(store_id)

    if sku:
        clauses.append("sku = ?")
        params.append(sku)

    if date_from:
        clauses.append("created_at >= ?")
        params.append(date_from)

    if date_to:
        clauses.append("created_at <= ?")
        params.append(date_to + "T23:59:59")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = get_db()
    total = conn.execute(
        f"SELECT COUNT(*) FROM investigations {where}", params
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(
        f"""SELECT * FROM investigations {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?""",
        [*params, per_page, offset],
    ).fetchall()
    conn.close()

    return PaginatedInvestigations(
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, math.ceil(total / per_page)),
        items=[_row_to_list_item(r) for r in rows],
    )


def update_status(
    investigation_id: int,
    new_status: InvestigationStatus,
    report: Optional[Report] = None,
    increment_iteration: bool = False,
) -> bool:
    """
    Called by the ReAct agent after each iteration and at end_turn.
    Must complete within 1 second (SRS constraint).
    Returns True if the row was found and updated, False otherwise.
    """
    now = _now()
    completed_at = now if new_status in (
        InvestigationStatus.COMPLETED,
        InvestigationStatus.ESCALATED,
    ) else None

    conn = get_db()
    with conn:
        affected = conn.execute(
            """UPDATE investigations
               SET status          = ?,
                   report          = ?,
                   updated_at      = ?,
                   completed_at    = COALESCE(?, completed_at),
                   iteration_count = iteration_count + ?
               WHERE id = ?""",
            (
                new_status.value,
                json.dumps(report.model_dump(mode="json")) if report else None,
                now,
                completed_at,
                1 if increment_iteration else 0,
                investigation_id,
            ),
        ).rowcount
        if affected:
            _audit(conn, investigation_id, "status_changed", new_status.value)
    conn.close()
    return affected > 0


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
    now = _now()
    conn = get_db()
    with conn:
        cur = conn.execute(
            """INSERT INTO tool_calls
               (investigation_id, tool_name, input_args, output, error, called_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                investigation_id,
                tool_name,
                json.dumps(input_args),
                json.dumps(output) if output is not None else None,
                error,
                now,
            ),
        )
        tc_id = cur.lastrowid
    conn.close()
    return tc_id
