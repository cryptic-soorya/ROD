import sqlite3, os

DB_PATH = os.getenv("SUPPLIERS_DB_PATH", "./mcp_server/db/suppliers.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS supplier_deliveries (
        supplier_id TEXT NOT NULL,
        period TEXT NOT NULL,
        avg_delivery_days_current REAL NOT NULL,
        avg_delivery_days_baseline REAL NOT NULL,
        defect_rate REAL NOT NULL,
        PRIMARY KEY (supplier_id, period)
    )
""")

seed_data = [
    ("SUP-019", "last_30_days", 11.4, 7.0, 0.034),
    ("SUP-019", "last_7_days",  12.1, 7.0, 0.041),
    ("SUP-019", "last_quarter", 9.2,  7.0, 0.028),
    ("SUP-022", "last_30_days", 6.8,  7.0, 0.012),
    ("SUP-022", "last_7_days",  7.1,  7.0, 0.015),
    ("SUP-031", "last_30_days", 14.5, 8.0, 0.067),
    ("SUP-031", "last_7_days",  15.2, 8.0, 0.082),
    ("SUP-045", "last_30_days", 5.0,  6.0, 0.008),
]

cursor.executemany("""
    INSERT OR REPLACE INTO supplier_deliveries
    (supplier_id, period, avg_delivery_days_current, avg_delivery_days_baseline, defect_rate)
    VALUES (?, ?, ?, ?, ?)
""", seed_data)

conn.commit()
conn.close()
print(f"suppliers.db seeded at {DB_PATH}")
