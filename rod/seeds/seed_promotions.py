import sqlite3, os

DB_PATH = os.getenv("PROMOTIONS_DB_PATH", "./mcp_server/db/promotions.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS promotions (
        promo_id TEXT PRIMARY KEY,
        sku TEXT NOT NULL,
        target_segment TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        projected_uplift_pct REAL NOT NULL,
        actual_uplift_pct REAL NOT NULL
    )
""")

promos = [
    ("PROMO-2026-01", "SKU-7782", "loyalty",    "2026-06-01", "2026-06-14", 25.0,  8.0),
    ("PROMO-2026-02", "SKU-3109", "new_users",  "2026-06-05", "2026-06-19", 20.0, 18.5),
    ("PROMO-2026-03", "SKU-4401", "all",        "2026-06-10", "2026-06-24", 15.0, 14.2),
    ("PROMO-2026-04", "SKU-7782", "all",        "2026-05-01", "2026-05-15", 30.0,  5.0),
    ("PROMO-2026-05", "SKU-3109", "loyalty",    "2026-04-10", "2026-04-24", 18.0, 17.1),
]

cursor.executemany("""
    INSERT OR REPLACE INTO promotions
    (promo_id, sku, target_segment, start_date, end_date, projected_uplift_pct, actual_uplift_pct)
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", promos)

conn.commit()
conn.close()
print(f"promotions.db seeded at {DB_PATH}")
