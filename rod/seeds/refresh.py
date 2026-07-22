import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv("AUTH_DB_URL", os.getenv("DATABASE_URL"))


def init_db() -> None:
    """Creates the auth.refresh_tokens table if it doesn't already exist.
    Safe to call on every startup."""
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE SCHEMA IF NOT EXISTS auth;

                    CREATE TABLE IF NOT EXISTS auth.refresh_tokens (
                        id          SERIAL PRIMARY KEY,
                        user_id     TEXT      NOT NULL,
                        token_hash  TEXT      NOT NULL,
                        expires_at  TIMESTAMP NOT NULL,
                        revoked     BOOLEAN   NOT NULL DEFAULT FALSE,
                        created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON auth.refresh_tokens(token_hash);
                    CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON auth.refresh_tokens(user_id);
                """)
    finally:
        conn.close()

    print("auth.refresh_tokens table ready in Postgres")


if __name__ == "__main__":
    init_db()