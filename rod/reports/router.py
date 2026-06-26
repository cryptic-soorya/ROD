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
