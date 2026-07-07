"""
main.py
OWNER: Team Lead

FastAPI app entry point.
Mounts all routers:
    - auth/router.py          → /auth
    - investigations/router.py→ /api/v1/detective
    - knowledge_base/router.py→ /api/v1/detective/knowledge   (SOORYA)
    - reports/router.py       → /api/v1/reports              (NOT MOUNTED — see below)

Start command: uvicorn main:app --port 8001 --reload

NOTE: mcp_server/server.py is an OPTIONAL standalone stdio MCP server for
      external MCP clients — it is NOT spawned by this app. During a real
      investigation, agent/react_loop.py imports and calls the tool functions
      in mcp_server/tools/*.py directly, in-process. Per-tool JWT scope
      enforcement (mcp_server/auth_middleware.py) is validated once here at
      startup and then checked inside each tool function itself, so it's
      enforced the same way regardless of which path calls the tool.
"""
from dotenv import load_dotenv

load_dotenv()

import os

from fastapi import FastAPI

from auth.router import router as auth_router
from investigations.router import router as investigations_router
from investigations.service import init_db as init_investigations_db
from mcp_server import auth_middleware
from logging_config import get_logger

logger = get_logger("main")

# knowledge_base/router.py exports a standalone FastAPI `app`, not an
# APIRouter (it was built to run as its own `uvicorn knowledge_api:app`
# process). Its endpoint paths are already absolute
# ("/api/v1/detective/knowledge..."), so its internal router is mounted
# here with no extra prefix. File is owned by SOORYA / marked DO NOT EDIT,
# so the adaptation happens here instead of there.
from knowledge_base.router import app as knowledge_app

app = FastAPI(title="ROD — Retail Operations Detective", version="1.0")


@app.on_event("startup")
def _startup() -> None:
    # Creates investigations/orchestration.db tables if they don't exist yet.
    init_investigations_db()

    # Validates the agent service token once so every MCP tool's check_scope()
    # call has a cached payload to check against. Exits the process (SystemExit)
    # if MCP_AUTH_TOKEN is missing/malformed/expired — no investigation could
    # gather evidence without it anyway, so failing fast at boot beats failing
    # per tool call.
    auth_middleware.startup_check(os.environ.get("MCP_AUTH_TOKEN", ""))

    logger.info("ROD API startup complete", extra={"event": "app_startup"})


app.include_router(auth_router)
app.include_router(investigations_router)
app.include_router(knowledge_app.router)

# reports/router.py is NOT mounted: it imports `utils.db.get_db_connection`,
# a module that doesn't exist anywhere in the repo, so importing it crashes
# the whole app at startup. Its endpoints also don't match the documented
# contract (GET /report/{investigationId}, /report/{id}/export) — it's a
# generic stub against a "reports" table. Needs a fix from Teammate E
# before it can be wired in:
# from reports.router import router as reports_router
# app.include_router(reports_router)


@app.get("/health", tags=["Meta"])
def health() -> dict:
    return {"status": "ok"}
