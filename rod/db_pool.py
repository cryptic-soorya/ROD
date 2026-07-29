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

RELIABILITY NOTE (2026-07-27): a plain psycopg2 ThreadedConnectionPool
hands back whatever connection object it's holding, dead or alive. If a
pooled connection has been sitting idle and Supabase's pooler (or a local
network blip / laptop sleep) closes the underlying socket in the
meantime, the connection object still *looks* fine to psycopg2 — the
first query run on it is what fails, with something like:

    psycopg2.DatabaseError: could not receive data from server:
    Can't assign requested address
    SSL SYSCALL error: Can't assign requested address

get_conn() validates a connection with a cheap `SELECT 1` before handing
it back — but ONLY if it's been sitting idle in the pool longer than
STALE_AFTER_SECONDS. Our DB is Supabase in ap-southeast-2, so every round
trip is expensive (~200-300ms+ from India); probing on every single
checkout — including connections that were just returned a moment ago —
was adding a full extra round trip to every request for no real benefit,
since a connection used seconds ago is not the one that goes stale. The
idle-time gate keeps the protection for the actual failure mode (a
connection that's been sitting unused long enough for Supabase's pooler
or the network to have dropped it) without taxing the common case.
"""

import time

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

_pools: dict[str, pg_pool.ThreadedConnectionPool] = {}

# How long a connection can sit idle in the pool before we bother
# re-validating it on checkout. Comfortably under Supabase pooler's idle
# timeout, but high enough that busy periods (the common case) skip the
# probe entirely.
STALE_AFTER_SECONDS = 20.0

# id(conn) -> time.monotonic() it was last returned to the pool. Purely an
# optimization hint, not a correctness guarantee — worst case we probe a
# connection unnecessarily (extra round trip) or skip probing one that's
# actually fine (put_conn's closed-check still catches broken ones on the
# way back in, and a genuinely dead one just surfaces the original error,
# unchanged from before this fix existed).
_returned_at: dict[int, float] = {}


def init_pools(dsns: list[str], minconn: int = 1, maxconn: int = 10) -> None:
    """Call once at app startup (FastAPI startup event) with every DSN
    your tool files use. Safe to pass duplicates — same DSN = same pool."""
    for dsn in set(dsns):
        if dsn and dsn not in _pools:
            _pools[dsn] = pg_pool.ThreadedConnectionPool(
                minconn, maxconn, dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
                # TCP keepalives so a socket that's idle in the pool is
                # actively probed by the OS, rather than silently rotting
                # until Supabase's pooler (or a network change) kills it
                # and we only find out on the next query.
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
            )


def _is_alive(conn) -> bool:
    """Cheap liveness probe. A connection can look fine to psycopg2's
    in-process state while the underlying TCP socket is already dead —
    the only way to know for sure is to actually round-trip a query."""
    if conn.closed:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except psycopg2.Error:
        return False


def get_conn(dsn: str, _retries: int = 2):
    """Returns a pooled connection. Only pays the extra round-trip cost of
    validating it if it's been idle long enough to plausibly have gone
    stale; a connection returned moments ago is handed back as-is."""
    if dsn not in _pools:
        # fallback: pool wasn't pre-registered (e.g. a DSN added later) —
        # spin one up lazily rather than crash.
        init_pools([dsn])

    pool = _pools[dsn]
    conn = pool.getconn()

    idle_for = time.monotonic() - _returned_at.get(id(conn), 0.0)
    if idle_for < STALE_AFTER_SECONDS or _is_alive(conn):
        return conn

    # Idle long enough that it failed the probe — discard (close=True tells
    # putconn to actually drop it instead of recycling it) and try again
    # with a fresh one instead of surfacing a hard 500 to the caller.
    _returned_at.pop(id(conn), None)
    pool.putconn(conn, close=True)
    if _retries <= 0:
        raise psycopg2.OperationalError(
            "db_pool: could not obtain a live connection after retries"
        )
    return get_conn(dsn, _retries=_retries - 1)


def put_conn(dsn: str, conn) -> None:
    # If the connection is already marked closed (e.g. the caller's query
    # died mid-flight with the same dead-socket error get_conn() guards
    # against on checkout), discard it instead of recycling a connection
    # we already know is bad back into the pool for the next caller to hit.
    if conn.closed:
        _returned_at.pop(id(conn), None)
        _pools[dsn].putconn(conn, close=True)
        return
    _returned_at[id(conn)] = time.monotonic()
    _pools[dsn].putconn(conn)


def close_all() -> None:
    """Call at app shutdown."""
    for p in _pools.values():
        p.closeall()