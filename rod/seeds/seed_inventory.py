import sqlite3, os

DB_PATH = os.getenv("INVENTORY_DB_PATH", "./mcp_server/db/inventory.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory_levels (
        sku TEXT NOT NULL,
        store_id TEXT NOT NULL,
        units_available INTEGER NOT NULL,
        units_reserved INTEGER NOT NULL,
        reorder_point INTEGER NOT NULL,
        last_updated TEXT NOT NULL,
        PRIMARY KEY (sku, store_id)
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS replenishment_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT NOT NULL,
        store_id TEXT NOT NULL,
        replenishment_date TEXT NOT NULL,
        quantity INTEGER NOT NULL
    )
""")

inventory_data = [
    ("SKU-3109", "STORE-01", 12,  3,  50, "2026-06-20"),
    ("SKU-3109", "STORE-02", 0,   0,  40, "2026-06-22"),
    ("SKU-7782", "STORE-01", 5,   2,  30, "2026-06-21"),
    ("SKU-7782", "STORE-03", 85,  10, 30, "2026-06-25"),
    ("SKU-4401", "STORE-01", 200, 15, 50, "2026-06-25"),
    ("SKU-4401", "STORE-04", 8,   1,  40, "2026-06-18"),
]

cursor.executemany("""
    INSERT OR REPLACE INTO inventory_levels
    (sku, store_id, units_available, units_reserved, reorder_point, last_updated)
    VALUES (?, ?, ?, ?, ?, ?)
""", inventory_data)

replenishment_data = [
    ("SKU-3109", "STORE-01", "2026-05-15", 60),
    ("SKU-3109", "STORE-01", "2026-06-01", 40),
    ("SKU-7782", "STORE-01", "2026-05-20", 50),
    ("SKU-4401", "STORE-01", "2026-04-10", 200),
    ("SKU-4401", "STORE-01", "2026-05-05", 150),
    ("SKU-4401", "STORE-01", "2026-06-10", 120),
]

cursor.executemany("""
    INSERT INTO replenishment_history (sku, store_id, replenishment_date, quantity)
    VALUES (?, ?, ?, ?)
""", replenishment_data)

conn.commit()
conn.close()
print(f"inventory.db seeded at {DB_PATH}")
