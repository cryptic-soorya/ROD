"""
reports/exporter.py
OWNER: Teammate E

export_to_pdf(report: dict) -> bytes
    Converts structured report JSON to PDF using reportlab.
    Must preserve evidence trail formatting for offline stakeholder sharing.

export_to_json(report: dict) -> dict
    Returns report dict as-is (identical to /report endpoint response).
"""
"""
reports/exporter.py
OWNER: Soorya

export_to_json() — trivial, returns Report as dict
export_to_pdf()  — generates PDF using reportlab
"""

import os
from investigations.models import Report


def export_to_json(report: Report) -> dict:
    """
    Returns the Report model as a plain dict.
    Identical to GET /report endpoint response body.
    """
    return report.model_dump(mode="json")


def export_to_pdf(report: Report, investigation_id: int) -> str:
    """
    Builds a PDF from the Report model using reportlab.
    Returns the file path of the generated PDF.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph,
        Spacer, Table, TableStyle, HRFlowable
    )

    os.makedirs("exports", exist_ok=True)
    filename = f"exports/INV-{investigation_id}-report.pdf"

    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm,   bottomMargin=2*cm
    )
    styles = getSampleStyleSheet()
    story  = []

    title_style = ParagraphStyle(
        "TitleCustom",
        parent=styles["Title"],
        fontSize=18,
        textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=6
    )
    heading_style = ParagraphStyle(
        "HeadingCustom",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=colors.HexColor("#16213e"),
        spaceBefore=12,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        "BodyCustom",
        parent=styles["Normal"],
        fontSize=10,
        spaceAfter=4
    )

    # SECTION 1 - Title
    story.append(Paragraph("ROD — Retail Operations Detective", title_style))
    story.append(Paragraph("Investigation Report", styles["Heading2"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
    story.append(Spacer(1, 0.3*cm))

    # SECTION 2 - Meta Table
    confidence_pct = (
        f"{report.confidence_score * 100:.0f}%"
        if report.confidence_score is not None else "N/A"
    )
    generated = (
        report.generated_at.strftime("%Y-%m-%d %H:%M UTC")
        if report.generated_at else "N/A"
    )
    category = (
        report.anomaly_category.value
        if report.anomaly_category else "N/A"
    )
    status = (
        "COMPLETED"
        if report.confidence_score and report.confidence_score >= 0.7
        else "ESCALATED"
    )

    meta_data = [
        ["Investigation ID",  str(investigation_id)],
        ["Status",            status],
        ["Anomaly Category",  category],
        ["Confidence Score",  confidence_pct],
        ["Generated At",      generated],
    ]
    meta_table = Table(meta_data, colWidths=[5*cm, 12*cm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0")),
        ("FONTNAME",   (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 10),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING",    (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.4*cm))

    # SECTION 3 - Root Cause
    story.append(Paragraph("Root Cause", heading_style))
    story.append(Paragraph(report.root_cause or "N/A", body_style))

    # SECTION 4 - Recommendations
    story.append(Paragraph("Recommendations", heading_style))
    if report.recommendations:
        for rec in report.recommendations:
            story.append(Paragraph(f"• {rec}", body_style))
    else:
        story.append(Paragraph("No recommendations recorded.", body_style))

    # SECTION 5 - Evidence Trail
    story.append(Paragraph("Evidence Trail", heading_style))
    if report.evidence_trail:
        for step in report.evidence_trail:
            story.append(Paragraph(f"• {step}", body_style))
            story.append(Spacer(1, 0.1*cm))
    else:
        story.append(Paragraph("No evidence recorded.", body_style))

    doc.build(story)
    return filename