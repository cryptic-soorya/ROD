import sqlite3, os

DB_PATH = os.getenv("CUSTOMERS_DB_PATH", "./mcp_server/db/customers.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS customer_complaints (
        complaint_id TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        complaint_date TEXT NOT NULL,
        description TEXT NOT NULL
    )
""")

complaints = [
    ("CMP-0001", "sizing",        "2026-06-10", "Ordered M, received a size that runs small — does not match size chart."),
    ("CMP-0002", "sizing",        "2026-06-11", "Size chart on listing is wrong. Returned immediately."),
    ("CMP-0003", "defective",     "2026-06-12", "Item arrived with broken zipper."),
    ("CMP-0004", "sizing",        "2026-06-13", "Size M fits like XS. Very misleading listing."),
    ("CMP-0005", "late_delivery", "2026-06-13", "Package arrived 8 days late with no updates."),
    ("CMP-0006", "sizing",        "2026-06-14", "Wrong size delivered. Size chart needs to be updated."),
    ("CMP-0007", "defective",     "2026-06-15", "Fabric quality is poor, pilling after first wash."),
    ("CMP-0008", "late_delivery", "2026-06-16", "Delivery estimate was 3 days, arrived on day 12."),
    ("CMP-0009", "sizing",        "2026-06-17", "Size chart is outdated. Returned."),
    ("CMP-0010", "wrong_item",    "2026-06-18", "Received completely different product than ordered."),
    ("CMP-0011", "sizing",        "2026-06-19", "Sizing inconsistent with other SKUs from same supplier."),
    ("CMP-0012", "late_delivery", "2026-06-20", "No update for 10 days. Had to contact support."),
    ("CMP-0013", "defective",     "2026-06-21", "SKU-7782 has a manufacturing defect on the seam."),
    ("CMP-0014", "sizing",        "2026-06-22", "Returned SKU-3109 — sizing guide on page is wrong."),
    ("CMP-0015", "late_delivery", "2026-06-23", "Third late delivery from same supplier this month."),
]

cursor.executemany("""
    INSERT OR REPLACE INTO customer_complaints
    (complaint_id, category, complaint_date, description)
    VALUES (?, ?, ?, ?)
""", complaints)

conn.commit()
conn.close()
print(f"customers.db seeded at {DB_PATH}")
