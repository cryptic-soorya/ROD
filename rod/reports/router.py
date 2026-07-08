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
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from auth.jwt_handler import verify_token
from investigations import service as investigations_service
from investigations.models import InvestigationStatus
from reports import service as reports_service
from reports.exporter import export_to_json, export_to_pdf

router = APIRouter(prefix="/api/v1/detective", tags=["Reports"])


def require_auth(payload: dict = Depends(verify_token)) -> dict:
    """Returns the decoded JWT payload. HTTPException raised by verify_token on failure."""
    return payload


def _load_report_or_404(investigation_id: int) -> dict:
    investigation = investigations_service.get_status(investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation {investigation_id} not found",
        )

    if investigation.status in (InvestigationStatus.PENDING, InvestigationStatus.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation {investigation_id} is still in progress",
        )

    report = reports_service.get_latest_report(str(investigation_id))
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report found for investigation {investigation_id}",
        )
    return report


def _human_readable_summary(report: dict) -> str:
    return (
        f"[{report.get('status', 'unknown').upper()}] {report.get('root_cause', '')} "
        f"(confidence: {report.get('confidence_score', 0.0):.2f})"
    )


@router.get(
    "/report/{investigation_id}",
    summary="Get the compiled report for an investigation",
)
def get_report(investigation_id: int, token_payload: dict = Depends(require_auth)):
    report = _load_report_or_404(investigation_id)
    return {**report, "human_readable_summary": _human_readable_summary(report)}


@router.get(
    "/report/{investigation_id}/export",
    summary="Export a report as JSON or PDF",
)
def export_report(
    investigation_id: int,
    format: str = Query("json", description="json | pdf"),
    token_payload: dict = Depends(require_auth),
):
    if format not in ("json", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format: {format!r}. Must be 'json' or 'pdf'.",
        )

    report = _load_report_or_404(investigation_id)

    if format == "json":
        return export_to_json(report)

    pdf_bytes = export_to_pdf(report)
    filename = f"INV-{investigation_id}-report.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
