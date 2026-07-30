"""
mcp_server/http_server.py

STANDALONE HTTP MCP SERVER — run via `python -m mcp_server.http_server`,
independently of the main FastAPI app (main.py) and independently of the
stdio entrypoint (`python -m mcp_server.server`).

This is agent/tools.py's REAL transport now: agent/tools.py's Client
connects to this process over an actual HTTP socket (MCP_SERVER_URL, default
http://127.0.0.1:8765/mcp) instead of the old in-memory FastMCPTransport that
wrapped mcp_server.server.mcp directly in the FastAPI app's own process. Same
`mcp` FastMCP instance, same 14 tool functions, same scope/RBAC enforcement
inside each tool body (mcp_server/tools/*.py, auth_middleware.py) — only the
wire between caller and server changed, from "same process, no socket" to
"two processes, a real loopback TCP connection".

Deploy/run this alongside main.py (e.g. as a second process in the same
compose/systemd unit, or a second container reachable at MCP_SERVER_URL) —
main.py does NOT spawn this itself, same as it never spawned the stdio
server.

CallerContext over this transport: see auth_middleware.py's "HTTP transport"
section. agent/tools.py sends the human caller's role/store_id as
X-Caller-Role / X-Caller-Store-Id headers per call; the middleware
registered below reads them and sets the ContextVar for that call.

Binds to 127.0.0.1 by default deliberately — this port now accepts real
network connections (unlike the in-memory transport it replaces), so it
should not be exposed beyond localhost/the deploying host without
additional transport-level auth in front of it (e.g. a reverse proxy, mTLS,
or a network policy scoping which hosts can reach it).
"""

import os

import db_pool
from logging_config import get_logger

from . import auth_middleware
from .server import mcp, TOOL_COUNT

logger = get_logger("mcp.http_server")


if __name__ == "__main__":
    # This process is now the only one that opens connections against the
    # per-tool DSNs (previously pooled by main.py's own startup, back when
    # the tool bodies ran in that process over the in-memory transport —
    # see main.py's _startup()). All fall back to DATABASE_URL.
    db_pool.init_pools([
        os.getenv("DATABASE_URL"),
        os.getenv("SALES_DB_URL", os.getenv("DATABASE_URL")),
        os.getenv("INVENTORY_DB_URL", os.getenv("DATABASE_URL")),
        os.getenv("RETURNS_DB_URL", os.getenv("DATABASE_URL")),
        os.getenv("CUSTOMERS_DB_URL", os.getenv("DATABASE_URL")),
        os.getenv("PROMOTIONS_DB_URL", os.getenv("DATABASE_URL")),
        os.getenv("SUPPLIERS_DB_URL", os.getenv("DATABASE_URL")),
    ])

    # Same single service-token validation as the stdio path (see
    # mcp_server/server.py's __main__) — one service token for this
    # process's whole lifetime, checked once at startup, independent of
    # per-investigation CallerContext (that's the middleware below, not
    # this call).
    auth_middleware.startup_check(os.environ.get("MCP_AUTH_TOKEN", ""))

    mcp.add_middleware(auth_middleware.make_caller_context_middleware())

    host = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_HTTP_PORT", "8765"))

    logger.info(
        "ROD MCP HTTP server starting",
        extra={"event": "mcp_http_server_start", "host": host, "port": port},
    )
    print(
        f"ROD MCP HTTP Server starting on http://{host}:{port}/mcp — "
        f"{TOOL_COUNT} tools registered, scope-checked per call"
    )
    try:
        mcp.run(transport="http", host=host, port=port)
    finally:
        db_pool.close_all()
