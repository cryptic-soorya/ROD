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

from fastapi import FastAPI

from auth.router import router as auth_router
from investigations.router import router as investigations_router
from reports.router import router as reports_router

app = FastAPI(title="ROD — Retail Operations Detective", version="1.0")

app.include_router(auth_router,           prefix="/auth",                    tags=["Auth"])
app.include_router(investigations_router, prefix="/api/v1/detective",        tags=["Investigations"])
app.include_router(reports_router,        prefix="/api/v1/detective/report", tags=["Reports"])

@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Retail Operations Detective Backend is running!"
    }