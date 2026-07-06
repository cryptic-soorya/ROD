import sqlite3

DB_PATH = "rod.db"

conn = sqlite3.connect(DB_PATH)

conn.execute("PRAGMA journal_mode=WAL")

conn.execute("""
    CREATE TABLE IF NOT EXISTS refresh_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        revoked BOOLEAN NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
""")

conn.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id)")

conn.commit()
conn.close()

print("refresh_tokens table created successfully.")