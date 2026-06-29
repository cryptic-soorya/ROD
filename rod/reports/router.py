"""
reports/router.py
OWNER: Teammate E

FastAPI router for:
- GET /api/v1/detective/report/{investigationId}
    Returns full report JSON + human_readable_summary field
    404 if investigation still in progress or doesn't exist

- GET /api/v1/detective/report/{investigationId}/export?format=pdf|json
    json → same as above response body
    pdf  → Content-Disposition: attachment; filename="INV-xxx-report.pdf"
    400 for unsupported format
"""
from fastapi import APIRouter
from utils.db import get_db_connection

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])

@router.get("/")
async def get_all_reports():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports")
    items = cursor.fetchall()
    conn.close()
    return [dict(item) for item in items]

@router.post("/")
async def create_report(title: str, status: str = "Pending"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reports (title, status) VALUES (?, ?)", (title, status))
    conn.commit()
    conn.close()
    return {"message": "Report entry saved successfully!"}