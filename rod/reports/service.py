"""
reports/service.py
OWNER: Teammate E (new — not previously defined in any shared file)

Persists compiled reports (the FRS Section 6.1 shape produced by
reports/generator.compile_report) into orchestrator.db's `reports` table,
so reports/router.py can serve GET /report/{id} and /report/{id}/export
without recomputing anything.

This file did not exist before — nothing was persisting compiled reports
anywhere queryable. Added as the missing link between react_loop's report
generation and the reports router. Flag if this should live elsewhere or
if `reports` should NOT live in orchestrator.db after all.
"""
import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "db", "orchestrator.db")
DB_PATH = os.path.abspath(DB_PATH)


def save_report(report: dict) -> dict:
    """
    Inserts a new versioned row for this investigation_id. Reports are
    immutable (per generator.py's docstring) — this never UPDATEs an
    existing row, only INSERTs a new version.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        investigation_id = report["investigation_id"]

        row = conn.execute(
            "SELECT MAX(version) FROM reports WHERE investigation_id = ?",
            (investigation_id,),
        ).fetchone()
        version = (row[0] or 0) + 1
        report_id = f"report-{investigation_id}-v{version}"

        conn.execute(
            """
            INSERT INTO reports (id, investigation_id, version, executive_summary, report_json, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                investigation_id,
                version,
                report["root_cause"][:500],
                json.dumps(report),
                report["generated_at"],
            ),
        )
        conn.commit()
        return {"id": report_id, "version": version}
    finally:
        conn.close()


def get_latest_report(investigation_id: str) -> dict | None:
    """Returns the highest-version compiled report for an investigation, or None."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE investigation_id = ? ORDER BY version DESC LIMIT 1",
            (investigation_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["report_json"])
    finally:
        conn.close()