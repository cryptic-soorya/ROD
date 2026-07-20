"""
seeds/db.py

Shared Postgres connection helper for all seed scripts.

Replaces the old per-file `sqlite3.connect(DB)` pattern. Since every
schema (auth, reference, sales, inventory, ...) now lives in ONE
Postgres database, there's exactly one connection to make — no more
ATTACH DATABASE dance, no more check_referential_integrity.py, because
Postgres enforces the FKs across schemas natively.

Connection string comes from DATABASE_URL env var, falling back to a
local trust-auth connection matching `createdb rod_db` / `psql rod_db`
(current OS user, no password, localhost).
"""

import os
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path)

DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    """One connection per script run. Caller is responsible for commit()/close()."""
    return psycopg2.connect(DATABASE_URL)


def bulk_insert(conn, table: str, columns: list[str], rows: list[tuple]) -> None:
    """
    table must be schema-qualified, e.g. 'reference.sku'.
    Uses execute_values for fast multi-row inserts (equivalent to
    sqlite3's executemany, but batched into one round-trip).
    """
    if not rows:
        return
    col_list = ", ".join(columns)
    sql = f"INSERT INTO {table} ({col_list}) VALUES %s ON CONFLICT DO NOTHING"
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)


def fetch_ids(conn, sql: str) -> list:
    """Runs a single-column SELECT and returns a flat list of values.
    Used by every downstream seed script to pull sku_id/store_id/etc.
    that seed_reference.py already inserted, instead of hardcoding
    id lists (which drift the moment reference data changes)."""
    with conn.cursor() as cur:
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


if __name__ == "__main__":
    # quick smoke test: confirm every schema is reachable
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'public')
            ORDER BY schema_name
        """)
        schemas = [r[0] for r in cur.fetchall()]
    conn.close()
    print("Reachable schemas:", schemas)