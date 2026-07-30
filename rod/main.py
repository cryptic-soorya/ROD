"""
main.py

FastAPI app entry point.
Mounts all routers:
    - auth/router.py          → /auth
    - investigations/router.py→ /api/v1/detective
    - knowledge_base/router.py→ /api/v1/detective/knowledge   (SOORYA)
    - reports/router.py       → /api/v1/detective/report(s)

Start command: uvicorn main:app --port 8001 --reload

NOTE (updated — MCP HTTP migration): mcp_server/server.py's `mcp` instance is
now run by TWO OTHER standalone processes, neither of which is this app:
  1. `python -m mcp_server.http_server` — the real MCP server for the live
     investigation path. agent/tools.py (used by agent/graph.py's LangGraph
     nodes) calls it over a genuine HTTP connection (MCP_SERVER_URL), not
     in-process — see agent/tools.py's module docstring for how
     CallerContext (store-scoped RBAC) now travels as HTTP headers instead
     of a shared contextvars.ContextVar.
  2. `python -m mcp_server.server` — the stdio entrypoint, for external MCP
     clients (e.g. Claude Desktop).
This app (main.py) does not import or run `mcp` at all anymore, and does
NOT spawn either of the above — both are separate deployables this process
talks to (path 1) or has nothing to do with (path 2). Per-tool JWT scope
enforcement (check_scope/get_token_payload in mcp_server/auth_middleware.py)
is validated once at startup inside WHICHEVER of those two processes is
actually running the tool, not here — this process never executes a tool
function body, so it has no cached token payload of its own to validate.
"""
from dotenv import load_dotenv

load_dotenv()

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.router import router as auth_router
from investigations.router import router as investigations_router
from reports.router import router as reports_router
from logging_config import get_logger
import db_pool

logger = get_logger("main")

# knowledge_base/router.py exports a standalone FastAPI `app`, not an
# APIRouter (it was built to run as its own `uvicorn knowledge_api:app`
# process). Its endpoint paths are already absolute
# ("/api/v1/detective/knowledge..."), so its internal router is mounted
# here with no extra prefix. File is owned by SOORYA / marked DO NOT EDIT,
# so the adaptation happens here instead of there.
from knowledge_base.router import app as knowledge_app

app = FastAPI(title="ROD — Retail Operations Detective", version="1.0")

# Frontend (Vite dev server) lives on a different origin. allow_credentials
# is required because /auth/refresh relies on an httpOnly cookie.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:

    # Open one pooled connection per unique DB DSN this process itself
    # queries directly (auth/, investigations/service.py, reports/service.py,
    # knowledge_base/). The per-tool DSNs (SALES_DB_URL, INVENTORY_DB_URL,
    # etc.) moved out of this list with the MCP HTTP migration: those tool
    # bodies now run exclusively inside mcp_server/http_server.py's own
    # process, which opens its own pools for them — this process never
    # queries those DSNs itself anymore. All fall back to DATABASE_URL, so
    # if none of these env vars are set individually this collapses to a
    # single pool.
    db_pool.init_pools([
        os.getenv("DATABASE_URL"),
        os.getenv("ORCHESTRATION_DB_URL", os.getenv("DATABASE_URL")),
        os.getenv("ROD_AUTH_DB_URL", os.getenv("DATABASE_URL")),
        os.getenv("KNOWLEDGE_DB_URL", os.getenv("DATABASE_URL")),
    ])

    logger.info("ROD API startup complete", extra={"event": "app_startup"})


@app.on_event("shutdown")
def _shutdown() -> None:
    db_pool.close_all()


app.include_router(auth_router)
app.include_router(investigations_router)
app.include_router(knowledge_app.router)
app.include_router(reports_router)


@app.get("/health", tags=["Meta"])
def health() -> dict:
    return {"status": "ok"}