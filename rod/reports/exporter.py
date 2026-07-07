"""
reports/exporter.py
OWNER: Teammate E

export_to_pdf(report: dict) -> bytes
    Converts structured report JSON to PDF using reportlab.
    Must preserve evidence trail formatting for offline stakeholder sharing.

export_to_json(report: dict) -> dict
    Returns report dict as-is (identical to /report endpoint response).

Requires: pip install reportlab --break-system-packages
"""

from io import BytesIO
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    ListFlowable,
    ListItem,
)
from reportlab.lib import colors


def export_to_json(report: dict) -> dict:
    """Returns the report dict unchanged — identical shape to the
    GET /report/{investigationId} response body. No transformation needed
    since the report is already the canonical structure."""
    return report


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        fontSize=18,
        leading=22,
        spaceAfter=12,
        textColor=colors.HexColor("#1a1a1a"),
    ))
    styles.add(ParagraphStyle(
        name="SectionHeader",
        fontSize=13,
        leading=16,
        spaceBefore=16,
        spaceAfter=8,
        textColor=colors.HexColor("#2b2b2b"),
    ))
    styles.add(ParagraphStyle(
        name="Body",
        fontSize=10.5,
        leading=15,
        alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="EvidenceFinding",
        fontSize=10,
        leading=14,
        leftIndent=10,
        textColor=colors.HexColor("#333333"),
    ))
    styles.add(ParagraphStyle(
        name="Meta",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#666666"),
    ))
    return styles


def _confidence_label(score: float) -> str:
    if score >= 0.75:
        return "High"
    if score >= 0.5:
        return "Medium"
    return "Low"


def export_to_pdf(report: dict) -> bytes:
    """
    Converts a report dict (as produced by generator.compile_report) into a
    formatted PDF, byte-encoded for direct HTTP response. Evidence trail is
    rendered as a numbered list with tool + finding per entry, preserving
    the step order for offline stakeholder review.
    """
    buffer = BytesIO()
    styles = _build_styles()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title=f"Investigation Report — {report.get('investigation_id', 'Unknown')}",
    )

    story = []

    # ── Header ──────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"Investigation Report: {report.get('investigation_id', 'Unknown')}",
        styles["ReportTitle"],
    ))

    confidence_score = report.get("confidence_score", 0.0)
    confidence_label = _confidence_label(confidence_score)

    meta_table_data = [
        ["Status", report.get("status", "—")],
        ["Anomaly Category", report.get("anomaly_category", "—")],
        ["Confidence Score", f"{confidence_score:.2f} ({confidence_label})"],
        ["Total Iterations", str(report.get("total_iterations", "—"))],
        ["Generated At", report.get("generated_at", "—")],
    ]
    meta_table = Table(meta_table_data, colWidths=[1.8 * inch, 4.2 * inch])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 16))

    # ── Root Cause ──────────────────────────────────────────────────────
    story.append(Paragraph("Root Cause", styles["SectionHeader"]))
    story.append(Paragraph(report.get("root_cause", "—"), styles["Body"]))

    # ── Estimated Impact ────────────────────────────────────────────────
    story.append(Paragraph("Estimated Impact", styles["SectionHeader"]))
    story.append(Paragraph(report.get("estimated_impact", "—"), styles["Body"]))

    # ── Evidence Trail ──────────────────────────────────────────────────
    story.append(Paragraph("Evidence Trail", styles["SectionHeader"]))
    evidence = report.get("evidence", [])
    if evidence:
        evidence_items = []
        for entry in evidence:
            step = entry.get("step", "?")
            tool = entry.get("tool", "unknown_tool")
            finding = entry.get("finding", "")
            evidence_items.append(
                ListItem(
                    Paragraph(f"<b>Step {step} — {tool}:</b> {finding}", styles["EvidenceFinding"]),
                    spaceAfter=6,
                )
            )
        story.append(ListFlowable(evidence_items, bulletType="1", leftIndent=14))
    else:
        story.append(Paragraph("No evidence entries recorded.", styles["Body"]))

    # ── Recommendations ─────────────────────────────────────────────────
    story.append(Paragraph("Recommendations", styles["SectionHeader"]))
    recommendations = report.get("recommendations", {})

    rec_sections = [
        ("Immediate Actions", recommendations.get("immediate", [])),
        ("Customer Recovery", recommendations.get("customer_recovery", [])),
        ("Process Improvement", recommendations.get("process_improvement", [])),
    ]

    for label, items in rec_sections:
        story.append(Paragraph(f"<b>{label}</b>", styles["Body"]))
        if items:
            rec_items = [
                ListItem(Paragraph(item, styles["Body"]))
                for item in items
            ]
            story.append(ListFlowable(rec_items, bulletType="bullet", leftIndent=14))
        else:
            story.append(Paragraph("None specified.", styles["Meta"]))
        story.append(Spacer(1, 6))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes