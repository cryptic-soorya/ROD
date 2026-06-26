"""
main.py
OWNER: Team Lead

FastAPI app entry point.
Mounts all routers:
    - auth/router.py          → /auth
    - investigations/router.py→ /api/v1/detective
    - knowledge_base/router.py→ /api/v1/detective/knowledge   (SOORYA)
    - reports/router.py       → /api/v1/detective/report

Start command: uvicorn main:app --port 8001 --reload

NOTE: MCP server (mcp_server/server.py) is a SEPARATE PROCESS.
      It is NOT mounted here. The agent spawns it via subprocess.
"""
from fastapi import FastAPI

app = FastAPI(title="ROD — Retail Operations Detective", version="1.0")

# Routers will be imported and mounted here as each module is completed:
# from auth.router import router as auth_router
# from investigations.router import router as investigations_router
# from knowledge_base.router import router as knowledge_router      # SOORYA — ready
# from reports.router import router as reports_router
