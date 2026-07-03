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

NOTE: MCP server (mcp_server/server.py) is a SEPARATE PROCESS.
      It is NOT mounted here. The agent spawns it via subprocess.
"""
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI

from auth.router import router as auth_router
from investigations.router import router as investigations_router
from investigations.service import init_db as init_investigations_db

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
