"""
seed_knowledge.py
Populates ChromaDB retail_kb collection with SOPs and Past Cases.
Run: python seeds/seed_knowledge.py

Deps: pip install chromadb sentence-transformers
"""

import random
from datetime import date, timedelta
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

CHROMA_PATH   = "knowledge_base/chroma_db"
COLLECTION    = "retail_kb"
EMBED_MODEL   = "all-MiniLM-L6-v2"

random.seed(42)

# ── SOPs ─────────────────────────────────────────────────────────────────────

SOPS = [
    {
        "id": "sop_001",
        "text": (
            "SOP: Handling Sudden Sales Drop\n"
            "When a product shows >30% revenue decline over 7 consecutive days: "
            "(1) Check inventory_levels for stockout. "
            "(2) Check recent product_listing_changes for price or description edits. "
            "(3) Check promotions that recently ended — post-promo crash is common. "
            "(4) Cross-reference customer_complaints for quality spikes. "
            "Escalate if root cause not found within 48h."
        ),
        "tags": "sales_drop,stockout,listing_change,post_promo_crash",
        "source_doc": "SOP_Sales_Anomaly_v3.pdf",
    },
    {
        "id": "sop_002",
        "text": (
            "SOP: Return Rate Spike Investigation\n"
            "If return rate exceeds 15% for any SKU in a 14-day window: "
            "(1) Pull return_reasons — dominant reason_code tells you where to look. "
            "(2) If 'not_as_described': check product_listing_changes for recent image/description edits. "
            "(3) If 'defective': escalate to supplier quality team, pull get_delivery_performance defect_rate. "
            "(4) If 'wrong_size': flag merchandising to update size guide. "
            "Raise low_sample_warning if sample_size < 10 before concluding anything."
        ),
        "tags": "returns,defective,wrong_size,not_as_described,supplier_quality",
        "source_doc": "SOP_Returns_Investigation_v2.pdf",
    },
    {
        "id": "sop_003",
        "text": (
            "SOP: Supplier Delivery Degradation\n"
            "degradation_flag=1 means avg_delivery_days_current > 1.5x baseline. "
            "(1) Identify all products sourced from flagged supplier via replenishment_history. "
            "(2) Check inventory_levels for those products — likely to see stockout_flag=1. "
            "(3) Alert procurement. Do not trigger emergency reorder until stockout confirmed. "
            "(4) If defect_rate also elevated (>0.1), escalate to vendor management immediately."
        ),
        "tags": "supplier,delivery,degradation,stockout,procurement",
        "source_doc": "SOP_Supplier_Management_v4.pdf",
    },
    {
        "id": "sop_004",
        "text": (
            "SOP: Promotion Performance Review\n"
            "After every promotion window closes: "
            "(1) Compute lift = units_sold / baseline_units. Lift < 1.2 = underperforming promo. "
            "(2) Check margin_impact — negative means promo destroyed value even if units were up. "
            "(3) Watch for post-promo sales crash in the 2 weeks after end_date. "
            "(4) If same product ran multiple promos in 30 days, flag for promo fatigue review."
        ),
        "tags": "promotion,lift,margin,post_promo_crash,promo_fatigue",
        "source_doc": "SOP_Promo_Review_v2.pdf",
    },
    {
        "id": "sop_005",
        "text": (
            "SOP: Customer Complaint Surge\n"
            "If complaint volume doubles week-over-week for a product or store: "
            "(1) Triage by category — shipping issues point to carrier/warehouse, quality to product/supplier. "
            "(2) High severity (severity=high) complaints always escalate same day. "
            "(3) Cross-check with return_reasons — complaints + returns together = strong quality signal. "
            "(4) Resolved=0 backlog above 20 for same product = operational bottleneck, escalate to ops."
        ),
        "tags": "complaints,quality,shipping,severity,escalation",
        "source_doc": "SOP_Complaint_Handling_v5.pdf",
    },
    {
        "id": "sop_006",
        "text": (
            "SOP: Stockout Prevention Protocol\n"
            "When stockout_flag=1 detected: "
            "(1) Immediately check replenishment_history — is there an open order pending? "
            "(2) If no open order, create emergency restock request flagged URGENT. "
            "(3) If open order exists, check received_date vs order_date delta — if >7 days, call supplier. "
            "(4) Consider inter-store transfer if adjacent store has stock_on_hand > 2x reorder_point."
        ),
        "tags": "stockout,replenishment,emergency_restock,inter_store_transfer",
        "source_doc": "SOP_Stockout_Prevention_v3.pdf",
    },
    {
        "id": "sop_007",
        "text": (
            "SOP: Confidence Score Escalation\n"
            "If agent confidence_score < 0.7 after ReAct loop completes: "
            "(1) Auto-set investigation status to 'escalated'. "
            "(2) Attach full evidence trail — do not summarise, attach raw tool_calls. "
            "(3) Human analyst reviews within 4 business hours. "
            "(4) Analyst may re-trigger investigation with additional context injected into anomaly_input."
        ),
        "tags": "confidence,escalation,human_review,react_loop",
        "source_doc": "SOP_Agent_Escalation_v1.pdf",
    },
    {
        "id": "sop_008",
        "text": (
            "SOP: Listing Change Rollback\n"
            "If product_listing_changes shows an edit within 3 days of a sales or returns anomaly: "
            "(1) Compare old_value vs new_value for the changed field. "
            "(2) If price increased >10%, that alone can explain sales drop — no further investigation needed. "
            "(3) If images changed and returns spiked with 'not_as_described', rollback images immediately. "
            "(4) All rollbacks logged in product_listing_changes with changed_by='rollback_bot'."
        ),
        "tags": "listing_change,rollback,price_increase,images,not_as_described",
        "source_doc": "SOP_Listing_Rollback_v2.pdf",
    },
]

# ── Past Cases ────────────────────────────────────────────────────────────────

PAST_CASES = [
    {
        "id": "case_001",
        "text": (
            "Past Case: P0042 Sales Drop — March 2025\n"
            "Observed 40% drop in units_sold for P0042 over 10 days. "
            "Root cause: supplier SUP07 had degradation_flag=1 (avg_delivery_days_current=12.3 vs baseline=4.1). "
            "This caused stockout_flag=1 in 8 stores. "
            "Resolution: emergency restock triggered, sales recovered within 6 days. "
            "Lesson: correlate sales drops with supplier degradation before assuming demand issue."
        ),
        "tags": "sales_drop,supplier_degradation,stockout,P0042,SUP07",
        "source_doc": "CaseReport_MAR2025_001.pdf",
    },
    {
        "id": "case_002",
        "text": (
            "Past Case: Returns Spike on P0117 — January 2025\n"
            "return_reasons showed 'not_as_described' as dominant reason_code (68% of returns). "
            "Investigation found product_listing_changes had images swapped 4 days prior by content_team. "
            "New images showed a different colour variant. "
            "Resolution: images rolled back, return rate normalised in 9 days. "
            "Lesson: always check listing changes within a 7-day window of a returns spike."
        ),
        "tags": "returns,not_as_described,listing_change,images,P0117",
        "source_doc": "CaseReport_JAN2025_002.pdf",
    },
    {
        "id": "case_003",
        "text": (
            "Past Case: Post-Promo Crash on P0089 — February 2025\n"
            "Sales dropped 55% in the 2 weeks after PROMO00234 ended (was a 40% discount promo). "
            "margin_impact was already negative during the promo (-$12,400). "
            "Post-promo, customers had stockpiled and demand collapsed. "
            "Resolution: no action taken, recovery natural by week 3. "
            "Lesson: negative margin_impact promos with high lift are high risk for post-promo crash."
        ),
        "tags": "promotion,post_promo_crash,margin_impact,P0089,promo_fatigue",
        "source_doc": "CaseReport_FEB2025_003.pdf",
    },
    {
        "id": "case_004",
        "text": (
            "Past Case: Complaint Surge at Store S012 — April 2025\n"
            "customer_complaints volume for S012 doubled in one week. Category: shipping (74%). "
            "Root cause: regional carrier outage caused delayed deliveries for all online orders routed through S012 warehouse. "
            "Resolution: orders rerouted to S018, backlog cleared in 4 days. "
            "Lesson: store-level complaint spikes in shipping category = carrier or warehouse issue, not product."
        ),
        "tags": "complaints,shipping,carrier,S012,warehouse",
        "source_doc": "CaseReport_APR2025_004.pdf",
    },
    {
        "id": "case_005",
        "text": (
            "Past Case: Defect Rate Spike from SUP14 — May 2025\n"
            "get_delivery_performance returned defect_rate=0.19 for SUP14 (baseline ~0.03). "
            "Affected products: P0023, P0071, P0134. "
            "Customer complaints showed 'defective' return_reason spiking concurrently. "
            "Resolution: SUP14 placed on quality hold, alternate supplier SUP03 used for emergency restocks. "
            "Lesson: defect_rate >0.1 from any supplier must trigger immediate cross-check with return_reasons."
        ),
        "tags": "supplier,defect_rate,returns,defective,SUP14,quality_hold",
        "source_doc": "CaseReport_MAY2025_005.pdf",
    },
    {
        "id": "case_006",
        "text": (
            "Past Case: Price Edit Caused Demand Drop on P0055 — June 2025\n"
            "product_listing_changes showed price increased from $34.99 to $54.99 by auto_sync on a Monday. "
            "units_sold dropped 62% the same week. No supplier issues, no returns spike. "
            "Resolution: price corrected back to $34.99, sales recovered next day. "
            "Lesson: isolate pricing changes first when sales drop has no inventory or quality signal."
        ),
        "tags": "price_increase,listing_change,sales_drop,P0055,auto_sync",
        "source_doc": "CaseReport_JUN2025_006.pdf",
    },
    {
        "id": "case_007",
        "text": (
            "Past Case: Low Sample Warning Misled Initial Investigation — March 2025\n"
            "return_reasons for P0198 showed 100% 'defective' return_reason — alarming. "
            "sample_size was 3 (only 3 units sold that period). low_sample_warning threshold not checked initially. "
            "Supplier quality hold issued prematurely. "
            "Resolution: hold lifted after wider sample confirmed defect_rate was normal. "
            "Lesson: always gate conclusions behind sample_size check. Never escalate on sample_size < 10."
        ),
        "tags": "low_sample_warning,returns,defective,sample_size,P0198,false_positive",
        "source_doc": "CaseReport_MAR2025_007.pdf",
    },
    {
        "id": "case_008",
        "text": (
            "Past Case: Multi-Signal Anomaly on P0067 — April 2025\n"
            "Simultaneous signals: sales_drop, returns_spike (wrong_size), complaint_surge (quality). "
            "Investigation found three independent causes: "
            "(1) size guide updated incorrectly — drove wrong_size returns. "
            "(2) A concurrent 20% discount promo ended — drove sales drop. "
            "(3) A bad batch from SUP09 — drove defective complaints. "
            "Resolution: size guide fixed, promo noted as resolved, SUP09 batch quarantined. "
            "Lesson: multi-signal anomalies often have multiple independent root causes. Do not stop at one."
        ),
        "tags": "multi_signal,sales_drop,returns,complaints,wrong_size,SUP09,P0067",
        "source_doc": "CaseReport_APR2025_008.pdf",
    },
    {
        "id": "case_009",
        "text": (
            "Past Case: Inventory Phantom Stock at S031 — May 2025\n"
            "inventory_levels showed stock_on_hand=120 but sales kept failing. "
            "Replenishment not triggered because stockout_flag never set. "
            "Physical audit found items were logged as received but never shelved — units_received in replenishment_history was inflated. "
            "Resolution: manual inventory correction, process audit for receiving workflow. "
            "Lesson: if sales are failing despite stock_on_hand > reorder_point, flag for physical audit."
        ),
        "tags": "inventory,phantom_stock,stockout,S031,receiving,audit",
        "source_doc": "CaseReport_MAY2025_009.pdf",
    },
    {
        "id": "case_010",
        "text": (
            "Past Case: Agent Escalation Due to Conflicting Signals — June 2025\n"
            "ReAct loop ran all 10 iterations, confidence_score=0.61 — auto-escalated. "
            "Signals contradicted each other: sales up but complaints up, returns down. "
            "Human analyst identified cause: a viral social media post drove new customer segment unfamiliar with product. "
            "Higher complaints from first-time buyers, but core customers retained. "
            "Lesson: external demand shocks are outside agent tool coverage. Escalation path worked correctly."
        ),
        "tags": "escalation,confidence,conflicting_signals,external_demand,social_media,human_review",
        "source_doc": "CaseReport_JUN2025_010.pdf",
    },
]

def random_past_date():
    start = date(2025, 1, 1)
    delta = (date(2026, 6, 30) - start).days
    import random as r
    return (start + timedelta(days=r.randint(0, delta))).isoformat()

def main():
    model = SentenceTransformer(EMBED_MODEL)

    client = chromadb.PersistentClient(
        path=CHROMA_PATH,
        settings=Settings(anonymized_telemetry=False),
    )
    col = client.get_or_create_collection(name=COLLECTION)

    all_docs     = SOPS + PAST_CASES
    ids          = [d["id"] for d in all_docs]
    texts        = [d["text"] for d in all_docs]
    metadatas    = [
        {
            "category":   "SOP" if d["id"].startswith("sop") else "Past Case",
            "tags":       d["tags"],
            "source_doc": d["source_doc"],
            "created_at": random_past_date(),
        }
        for d in all_docs
    ]

    embeddings = model.encode(texts, show_progress_bar=True).tolist()

    col.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)

    print(f"retail_kb seeded -> {col.count()} documents ({len(SOPS)} SOPs + {len(PAST_CASES)} Past Cases)")

if __name__ == "__main__":
    main()