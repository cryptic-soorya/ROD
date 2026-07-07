# test_report.py
from reports.generator import compile_report
from reports.exporter import export_to_pdf, export_to_json

fake_evidence = [
    {"step": 1, "tool": "get_sales_data", "finding": "Units sold dropped 42% over 7 days for P0042."},
    {"step": 2, "tool": "get_supplier_delivery", "finding": "Supplier SUP07 showed degradation_flag=1, avg delivery days 12.3 vs baseline 4.1."},
    {"step": 3, "tool": "get_inventory_levels", "finding": "Stockout confirmed at 8 stores during the affected window."},
]

fake_agent_summary = {
    "root_cause": "Supplier SUP07 delivery degradation caused stockouts, driving the sales drop.",
    "anomaly_category": "sales_drop",
    "estimated_impact": "Estimated $18,400 in lost revenue over the 7-day window.",
    "status": "completed",
    "recommendations": {
        "immediate": ["Trigger emergency restock for P0042 across affected stores."],
        "customer_recovery": ["Notify customers on backorder with revised ETA."],
        "process_improvement": ["Add automatic alerting when supplier degradation_flag flips to 1."],
    },
}

report = compile_report(
    investigation_id="inv-0001",
    evidence_trail=fake_evidence,
    agent_summary=fake_agent_summary,
    confidence_score=0.87,
)

print("compile_report() output:")
print(report)

# Test JSON export
json_result = export_to_json(report)
assert json_result == report
print("\nexport_to_json() passthrough: OK")

# Test PDF export
pdf_bytes = export_to_pdf(report)
with open("test_report.pdf", "wb") as f:
    f.write(pdf_bytes)
print(f"\nexport_to_pdf() wrote {len(pdf_bytes)} bytes to test_report.pdf")