"""
reports/service.py
OWNER: Teammate E

Persists compiled reports (the FRS Section 6.1 shape produced by
reports/generator.compile_report) into Postgres's orchestration.reports
table, so reports/router.py can serve GET /report/{id} and
/report/{id}/export without recomputing anything.

SCHEMA NOTE (2026-07-20): migrated off the old local SQLite
investigations/orchestration.db onto the same Postgres `orchestration`
schema investigations/service.py uses — that sqlite file was a pre-Postgres
leftover and was never actually the same table as the one
investigations.service.update_status() writes reports into. Both this
module and investigations.service now write into the same physical
orchestration.reports table (each producing its own version row per
investigation — see agent/orchestrator.run()'s docstring for why both write).

reports.id is a text PK with no identity default (unlike tool_calls/
audit_logs), so this module generates its own id, same convention
investigations.service.update_status() uses (there it's a uuid; here it
keeps the previous report-{investigation_id}-v{version} format since that's
a stable, human-readable id and nothing else depended on it being a uuid).
"""
import json

from investigations.service import get_db


def save_report(report: dict) -> dict:
    """
    Inserts a new versioned row for this investigation_id. Reports are
    immutable (per generator.py's docstring) — this never UPDATEs an
    existing row, only INSERTs a new version.
    """
    investigation_id = int(report["investigation_id"])

    conn = get_db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(version), 0) AS v FROM orchestration.reports "
                    "WHERE investigation_id = %s",
                    (investigation_id,),
                )
                version = cur.fetchone()["v"] + 1
                report_id = f"report-{investigation_id}-v{version}"

                cur.execute(
                    """INSERT INTO orchestration.reports
                       (id, investigation_id, version, executive_summary, report_json, generated_at)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        report_id,
                        investigation_id,
                        version,
                        report["root_cause"][:500],
                        json.dumps(report),
                        report["generated_at"],
                    ),
                )
        return {"id": report_id, "version": version}
    finally:
        conn.close()


def get_latest_report(investigation_id: int) -> dict | None:
    """Returns the highest-version compiled report for an investigation, or None."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM orchestration.reports
                   WHERE investigation_id = %s
                   ORDER BY version DESC
                   LIMIT 1""",
                (int(investigation_id),),
            )
            row = cur.fetchone()
        if row is None:
            return None
        report_json = row["report_json"]
        return json.loads(report_json) if isinstance(report_json, str) else report_json
    finally:
        conn.close()