"""
db_pool.py

One psycopg2 connection pool per unique DSN, created once at app startup
and reused everywhere instead of every tool file opening its own
connection per call.

Usage in a tool file:
    from db_pool import get_conn, put_conn

    conn = get_conn(DB_DSN)
    try:
        ...
    finally:
        put_conn(DB_DSN, conn)
"""

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

_pools: dict[str, pg_pool.ThreadedConnectionPool] = {}


def init_pools(dsns: list[str], minconn: int = 1, maxconn: int = 10) -> None:
    """Call once at app startup (FastAPI startup event) with every DSN
    your tool files use. Safe to pass duplicates — same DSN = same pool."""
    for dsn in set(dsns):
        if dsn and dsn not in _pools:
            _pools[dsn] = pg_pool.ThreadedConnectionPool(
                minconn, maxconn, dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )


def get_conn(dsn: str):
    if dsn not in _pools:
        # fallback: pool wasn't pre-registered (e.g. a DSN added later) —
        # spin one up lazily rather than crash.
        init_pools([dsn])
    return _pools[dsn].getconn()


def put_conn(dsn: str, conn) -> None:
    _pools[dsn].putconn(conn)


def close_all() -> None:
    """Call at app shutdown."""
    for p in _pools.values():
        p.closeall()