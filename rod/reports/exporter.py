"""
reports/exporter.py
OWNER: Teammate E

export_to_pdf(report: dict) -> bytes
    Converts structured report JSON to PDF using reportlab.
    Must preserve evidence trail formatting for offline stakeholder sharing.

export_to_json(report: dict) -> dict
    Returns report dict as-is (identical to /report endpoint response).
"""
