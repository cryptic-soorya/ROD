"""
seeds/seed_anomaly_customer.py

Injects one deliberate, coherent customer_complaint anomaly.

NO sku_id/store_id CHANGE NEEDED: unlike the other three anomaly scripts,
this table never had product_id/store_id in the first place -- see the
schema note below, which is what caught (and fixed) that seed_customers.py
had been generating the wrong schema all along.

SCHEMA NOTE (now fixed): seed_customers.py previously declared
customer_complaints(id, product_id/sku_id, store_id, severity,
complaint_text, resolved), which never matched what
mcp_server/tools/customers.py actually queries -- its category-filtered
SELECT reads `complaint_id` and `description`, neither of which existed
under that schema. seed_customers.py has been corrected to the real
shape: customer_complaints(complaint_id TEXT PRIMARY KEY, category,
complaint_date, description). This script targets that corrected schema.

Because this table has no sku_id/store_id, there is still no way for this
scenario to name a specific affected product or store the way the other
three engineered anomalies do -- that's a real characteristic of this
table, not an oversight in this script.

Scenario: a wave of "wrong_item" complaints (fulfillment/picking mistakes)
over the last ~10 days.

Evidence this leaves for the agent's tools to find:
  - get_customer_complaints(date_range="<~14 days ago>,<today>")
        -> grouped_by_category shows "wrong_item" as dominant_category,
           with volume clearly above baseline for every other category
           in the same window.

Root cause / confidence rationale: this category has exactly one working
tool (get_customer_complaints), so there is no second, independent tool
call to corroborate against. Expect the agent to land around 0.75-0.84
confidence here, not 0.85+, per agent/prompts.py's rubric -- that's the
honest, correct outcome given the data available, not a bug.

Run from the rod/ directory:
    python seeds/seed_anomaly_customer.py

Safe to re-run: deletes-then-reinserts only its own reserved complaint_id
range ("CMP-ANOM-*").
"""
import os
import sqlite3
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUSTOMERS_DB = os.path.join(BASE_DIR, "mcp_server", "db", "customers.db")

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
