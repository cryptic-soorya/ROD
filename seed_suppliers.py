# seed_suppliers.py
# This script creates suppliers.db and fills it with fake but realistic data.
# Run once: python seed_suppliers.py

import sqlite3

# Connect to (or create) the database file
conn = sqlite3.connect("suppliers.db")
cursor = conn.cursor()

# Create the table
# supplier_id: e.g. "SUP-019"
# period: e.g. "last_30_days"
# avg_delivery_days_current: how long deliveries are taking NOW
# avg_delivery_days_baseline: how long they normally take (the healthy benchmark)
# defect_rate: fraction of deliveries with defects (0.034 = 3.4%)
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

# Seed data — mix of healthy and degraded suppliers
seed_data = [
    # (supplier_id, period, current_days, baseline_days, defect_rate)
    ("SUP-019", "last_30_days", 11.4, 7.0, 0.034),   # degraded (11.4 > 1.5 × 7.0 = 10.5)
    ("SUP-019", "last_7_days",  12.1, 7.0, 0.041),   # also degraded
    ("SUP-019", "last_quarter", 9.2,  7.0, 0.028),   # borderline
    ("SUP-022", "last_30_days", 6.8,  7.0, 0.012),   # healthy (under baseline)
    ("SUP-022", "last_7_days",  7.1,  7.0, 0.015),   # healthy
    ("SUP-031", "last_30_days", 14.5, 8.0, 0.067),   # very degraded
    ("SUP-031", "last_7_days",  15.2, 8.0, 0.082),   # very degraded
    ("SUP-045", "last_30_days", 5.0,  6.0, 0.008),   # outperforming
]

cursor.executemany("""
    INSERT OR REPLACE INTO supplier_deliveries
    (supplier_id, period, avg_delivery_days_current, avg_delivery_days_baseline, defect_rate)
    VALUES (?, ?, ?, ?, ?)
""", seed_data)

conn.commit()
conn.close()
print("suppliers.db created and seeded.")