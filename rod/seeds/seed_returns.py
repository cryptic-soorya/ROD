import sqlite3, os

DB_PATH = os.getenv("RETURNS_DB_PATH", "./mcp_server/db/returns.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS return_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT NOT NULL,
        return_date TEXT NOT NULL,
        reason TEXT NOT NULL
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_listing_changes (
        sku TEXT NOT NULL PRIMARY KEY,
        last_updated TEXT NOT NULL,
        supplier_change_date TEXT NOT NULL,
        fields_changed TEXT NOT NULL
    )
""")

return_events = [
    ("SKU-3109", "2026-06-10", "wrong_size"),
    ("SKU-3109", "2026-06-11", "wrong_size"),
    ("SKU-3109", "2026-06-12", "wrong_size"),
    ("SKU-3109", "2026-06-13", "wrong_size"),
    ("SKU-3109", "2026-06-13", "wrong_size"),
    ("SKU-3109", "2026-06-14", "defective"),
    ("SKU-3109", "2026-06-14", "wrong_size"),
    ("SKU-3109", "2026-06-15", "wrong_size"),
    ("SKU-3109", "2026-06-15", "changed_mind"),
    ("SKU-3109", "2026-06-16", "wrong_size"),
    ("SKU-3109", "2026-06-17", "wrong_size"),
    ("SKU-3109", "2026-06-18", "defective"),
    ("SKU-7782", "2026-06-20", "defective"),
    ("SKU-7782", "2026-06-21", "defective"),
    ("SKU-7782", "2026-06-22", "wrong_size"),
    ("SKU-4401", "2026-06-23", "changed_mind"),
    ("SKU-4401", "2026-06-24", "changed_mind"),
]

cursor.executemany("""
    INSERT INTO return_events (sku, return_date, reason)
    VALUES (?, ?, ?)
""", return_events)

listing_data = [
    ("SKU-3109", "2026-05-28", "2026-05-07", "size_chart,material"),
    ("SKU-7782", "2026-06-24", "2026-06-23", "color_options"),
    ("SKU-4401", "2026-06-25", "2026-06-25", "description"),
]

cursor.executemany("""
    INSERT OR REPLACE INTO product_listing_changes
    (sku, last_updated, supplier_change_date, fields_changed)
    VALUES (?, ?, ?, ?)
""", listing_data)

conn.commit()
conn.close()
print(f"returns.db seeded at {DB_PATH}")
