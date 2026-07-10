"""
seeds/seed_anomaly_customer.py

Injects one deliberate, coherent CUSTOMER_COMPLAINT anomaly, following the
same convention as seed_anomaly.py (SUP07/S036/P0108 -> supplier_delay).
The base random seed data has no engineered customer_complaint signal — see
CLAUDE.md's "Seeded anomalies" section.

Scenario: a wave of "wrong_item" complaints (fulfillment/picking mistakes —
the customer received a different item than what they ordered) over the
last ~10 days. This is deliberately NOT tied to a specific product or
store — see the schema note below — it is written up as a company-wide
fulfillment-process issue, which is exactly the kind of root cause
agent/prompts.py describes for this category ("a pattern in customer
complaints ... packaging, delivery experience ... rather than the other
categories").

Evidence this leaves for the agent's tools to find:
  - get_customer_complaints(date_range="<~14 days ago>,<today>")
        -> grouped_by_category shows "wrong_item" as dominant_category,
           with total volume clearly above the pre-existing baseline for
           every other category in the same window (organic customers.db
           only had 15 total complaints across its whole recorded history
           before this script ran — see schema note below).

IMPORTANT SCHEMA NOTE (found while writing this script, not something this
script fixes): the LIVE customers.db does not match seeds/seed_customers.py.
The real table is `customer_complaints(complaint_id TEXT PRIMARY KEY,
category, complaint_date, description)` — no product_id, store_id,
severity, or resolved columns, unlike what seed_customers.py's SCHEMA
constant declares. mcp_server/tools/customers.py's get_customer_complaints
also has a real bug on this live schema: the `category=` filtered query
selects `id AS complaint_id` and `complaint_text AS description`, columns
that don't exist on the live table, so calling it WITH a category filter
raises `sqlite3.OperationalError: no such column: id` (confirmed by
running it directly). Only the no-category grouped-by-category path
actually works. This script targets that working path only, and does not
attempt to fix mcp_server/tools/customers.py (owned by Teammate D) or
seed_customers.py — flagging it here so whoever owns that file sees it.
Because the live schema has no product_id/store_id, there is also no way
for this scenario to name a specific affected product or store the way
the other three engineered anomalies do — that's a real limitation of the
current schema, not an oversight in this script.

Root cause / confidence rationale: this category has exactly one working
tool (get_customer_complaints), so there is no second, independent tool
call to corroborate against — unlike the other three engineered anomalies.
The signal itself (many individual complaint records, not just one
aggregate flag, all landing in one category against a near-empty
baseline) is unambiguous, but per agent/prompts.py's rubric this is "strong
evidence pointing to one explanation with no major contradictions" rather
than "multiple independent pieces of evidence" — expect the agent to land
around 0.75-0.84 confidence here, not 0.85+, and that's the honest,
correct outcome given the data available, not a bug in this seed script.

Run from the rod/ directory, same convention as the other seeds/*.py:
    python seeds/seed_anomaly_customer.py

Safe to re-run: deletes-then-reinserts only its own reserved complaint_id
range ("CMP-ANOM-*") rather than touching anything else.
"""
import sqlite3
from datetime import date, timedelta

CUSTOMERS_DB = "mcp_server/db/customers.db"

TODAY = date.today()

DESCRIPTIONS = [
    "Ordered the blue version, received a completely different product.",
    "Package contained the wrong SKU entirely — not even close to what I ordered.",
    "Received someone else's order, not mine.",
    "Wrong item shipped again — this is the second time this month.",
    "Box had the right label but the wrong product inside.",
]


def seed_complaint_wave(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM customer_complaints WHERE complaint_id LIKE 'CMP-ANOM-%'")

    rows = []
    for i in range(18):
        complaint_id = f"CMP-ANOM-{i + 1:03d}"
        complaint_date = (TODAY - timedelta(days=10 - (i % 10))).isoformat()
        description = DESCRIPTIONS[i % len(DESCRIPTIONS)]
        rows.append((complaint_id, "wrong_item", complaint_date, description))

    conn.executemany(
        "INSERT INTO customer_complaints (complaint_id, category, complaint_date, description) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    print(f"customer_complaints: inserted {len(rows)} wrong_item complaints over the last 10 days")


def main() -> None:
    conn = sqlite3.connect(CUSTOMERS_DB)
    try:
        seed_complaint_wave(conn)
        conn.commit()
    finally:
        conn.close()

    window_start = (TODAY - timedelta(days=14)).isoformat()
    print(f"\nDone. Investigate with date_range='{window_start},{TODAY.isoformat()}' to exercise this customer_complaint case.")


if __name__ == "__main__":
    main()
