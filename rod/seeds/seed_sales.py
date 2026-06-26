import sqlite3, os

DB_PATH = os.getenv("SALES_DB_PATH", "./mcp_server/db/sales.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS store_sales (
        store_id TEXT NOT NULL,
        period TEXT NOT NULL,
        revenue_current_period REAL NOT NULL,
        revenue_previous_period REAL NOT NULL,
        PRIMARY KEY (store_id, period)
    )
""")

seed_data = [
    ("STORE-01", "last_30_days", 142500.0, 138200.0),
    ("STORE-01", "last_7_days",  31200.0,  34500.0),
    ("STORE-02", "last_30_days", 98400.0,  101200.0),
    ("STORE-02", "last_7_days",  22100.0,  24800.0),
    ("STORE-03", "last_30_days", 210000.0, 195000.0),
    ("STORE-03", "last_7_days",  47300.0,  46100.0),
    ("STORE-04", "last_30_days", 67800.0,  89200.0),
    ("STORE-04", "last_7_days",  14200.0,  20100.0),
]

cursor.executemany("""
    INSERT OR REPLACE INTO store_sales
    (store_id, period, revenue_current_period, revenue_previous_period)
    VALUES (?, ?, ?, ?)
""", seed_data)

conn.commit()
conn.close()
print(f"sales.db seeded at {DB_PATH}")
