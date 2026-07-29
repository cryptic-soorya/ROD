"""
seed_knowledge.py
Populates the shared Postgres/pgvector retail_kb table (knowledge.chunks,
see knowledge_base/pg_vector_client.py) with SOPs and Past Cases. Everyone
on the team points at the same Supabase DB, so running this once seeds
the knowledge base for the whole team, not just the machine it runs on.

main() deletes every existing row before inserting the current SOPS/
PAST_CASES lists below, so re-running this script fully replaces the
knowledge base rather than appending to it.

Content note (2026-07-29): Past Cases deliberately do NOT name specific
store/SKU/supplier/promo ids. Two reasons: (1) the previous version of
this file hardcoded ids like "P0042"/"SUP07" that never existed in the
live Postgres data and don't even match the id formats agent/grounding.py
expects (real skus are "P0030-SKU01", not "P0042"), which let the agent
either chase a dead lead or, worse, cite the Past Case's fabricated id
directly in its root_cause since grounding.py only checks that a claimed
id appeared *somewhere* in the evidence trail -- a knowledge_search hit
counts. Naming a real id in a Past Case creates exactly that shortcut:
the agent can satisfy grounding by quoting the case instead of
independently confirming it against this investigation's own tool calls.
Past Cases here describe the pattern and the reasoning instead, so the
model has to go pull a real id via its own tool calls. See sop_008 below,
which states this rule explicitly for the agent itself. (2) the specific
sku/store ids used by seeds/seed_anomaly.py's five scenarios are chosen
dynamically at seed time from whatever's in reference.sku/reference.stores,
so hardcoding today's picks would go stale on the next reseed anyway.

Run: python seeds/seed_knowledge.py

Deps: pip install pgvector psycopg2-binary sentence-transformers
"""

import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from knowledge_base.chunking import chunk_text
from knowledge_base.service import get_collection

random.seed(42)

# ── SOPs ─────────────────────────────────────────────────────────────────────

SOPS = [
    {
        "id": "sop_001",
        "text": (
            "SOP: Sales Drop Investigation\n"
            "When a store or SKU shows a meaningful revenue decline: "
            "(1) If no specific store/SKU was named, use get_stores_with_sales_decline (or "
            "get_stores_with_sku_decline for a SKU-wide pattern across stores) to find the "
            "affected entity first — never guess or invent one. get_top_declining_skus_for_store "
            "narrows further once a store is identified. "
            "(2) Check get_inventory_levels for a stockout on that sku/store. "
            "(3) Check get_product_listing_changes for a recent price/description/image edit. "
            "(4) Check get_promotion_performance / get_underperforming_promotions for a promo that "
            "recently ended — a post-promo pull-forward crash is a real pattern. "
            "(5) Check get_customer_complaints for a concurrent quality or shipping spike. "
            "A sales drop with none of the above present is a valid outcome, not a failure to look "
            "hard enough — see the 'unexplained decline' guidance under confidence scoring."
        ),
        "tags": "sales_drop,discovery,stockout,listing_change,post_promo",
        "source_doc": "SOP_Sales_Anomaly_v4.pdf",
    },
    {
        "id": "sop_002",
        "text": (
            "SOP: Return Rate Spike Investigation\n"
            "get_return_reasons(sku, days, store_id) returns a breakdown of reason_code -> share of "
            "returns (percentages sum to ~1.0) plus total_returns and low_sample_warning. "
            "low_sample_warning is true whenever total_returns < 10 for the window queried — treat any "
            "conclusion drawn while that flag is true as provisional, and say so rather than presenting "
            "it as confirmed. store_id is optional: omit it to aggregate across every store carrying the "
            "SKU, or pass a specific store when a store-level bad batch or handling issue is suspected — "
            "aggregating away the store dimension can dilute a real, localized spike into noise. "
            "Once the dominant reason_code is known: "
            "'wrong_size' or a sizing-related reason -> check get_product_listing_changes for a recent "
            "size_chart/size_guide edit on that SKU. "
            "'not_as_described' -> check get_product_listing_changes for a recent description/images edit. "
            "'defective' -> check get_delivery_performance for the SKU's supplier — an elevated defect_rate "
            "corroborates a quality-driven return spike."
        ),
        "tags": "returns,low_sample_warning,wrong_size,not_as_described,defective",
        "source_doc": "SOP_Returns_Investigation_v3.pdf",
    },
    {
        "id": "sop_003",
        "text": (
            "SOP: Supplier Delivery Degradation\n"
            "get_delivery_performance's degradation_flag is true when avg_delivery_days_current > 1.5x "
            "avg_delivery_days_baseline for the requested period (last_7_days / last_30_days / "
            "last_quarter). "
            "(1) When a degraded supplier is found, trace which specific sku/store combinations it "
            "supplies via get_replenishment_history before assuming every product from that supplier is "
            "affected — a claim linking a supplier to a specific store's stockout needs a tool result that "
            "actually names both together, not two separately-true facts stitched by inference. "
            "(2) Check get_inventory_levels for those sku/store pairs for an actual stockout, rather than "
            "assuming one follows automatically from a delayed shipment. "
            "(3) If defect_rate is also elevated alongside degradation_flag, treat that as a second, "
            "independent signal worth calling out on its own rather than folding it silently into the "
            "delivery-delay narrative."
        ),
        "tags": "supplier,delivery,degradation,defect_rate,stockout",
        "source_doc": "SOP_Supplier_Management_v5.pdf",
    },
    {
        "id": "sop_004",
        "text": (
            "SOP: Promotion Performance Review\n"
            "get_promotion_performance(promo_id) computes actual_uplift_pct = (units_sold - "
            "baseline_units) / baseline_units * 100, and projected_uplift_pct from discount_pct "
            "(roughly discount_pct x 2). underperformance_flag is true when actual_uplift_pct < 0.5 x "
            "projected_uplift_pct — a promo can still show a modest positive lift and be flagged, so "
            "check the flag directly rather than eyeballing whether units went up at all. "
            "When the specific promo_id isn't already known, get_underperforming_promotions(store_id, "
            "period_days, limit) is the discovery entry point — it ranks by worst shortfall_pct first. "
            "Also check margin_impact: a promo can hit its uplift target and still be negative-margin, "
            "which is a separate problem from underperformance and should be reported as such. "
            "Comparing against the same SKU's other promo history (a second get_promotion_performance "
            "call against a different promo_id) helps rule out 'this SKU just doesn't respond to "
            "promotions' as an alternative explanation before concluding this specific promo failed."
        ),
        "tags": "promotion,uplift,underperformance_flag,margin_impact,discovery",
        "source_doc": "SOP_Promo_Review_v3.pdf",
    },
    {
        "id": "sop_005",
        "text": (
            "SOP: Customer Complaint Investigation\n"
            "get_customer_complaints(sku_id, store_id, date_range, category) filters are all optional and "
            "combinable. Calling it with no category returns grouped_by_category counts — use this first "
            "to see which category dominates (shipping, quality, wrong_item, etc.) before drilling in. "
            "Calling it with category set returns individual complaint records, each carrying its own "
            "sku_id/store_id, which lets you check whether complaints actually concentrate on a specific "
            "SKU or store rather than being spread evenly. "
            "A shipping-category spike concentrated at one store points to a carrier/warehouse issue at "
            "that store, not a product problem — confirm this by re-running the grouped call scoped to "
            "that store_id and checking shipping's share there specifically, rather than citing a similar "
            "pattern from memory without checking this investigation's own complaint data. "
            "A quality/defective-category spike concentrated on one SKU pairs well with a "
            "get_delivery_performance check on that SKU's supplier."
        ),
        "tags": "complaints,shipping,quality,discovery,store_scoped",
        "source_doc": "SOP_Complaint_Handling_v6.pdf",
    },
    {
        "id": "sop_006",
        "text": (
            "SOP: Inventory Anomaly Investigation (stockout and over-ordering)\n"
            "get_inventory_levels(sku, store_id) and get_low_stock_items_for_store(store_id, limit) cover "
            "the stockout side: stock_on_hand at or below reorder_point. "
            "(1) When stock is low, check get_replenishment_history for an open order — if none exists, "
            "flag for an emergency restock; if one exists, compare received_date to order_date and escalate "
            "to the supplier if the gap is unusually long. "
            "(2) The opposite anomaly is just as real and easy to miss: stock_on_hand sitting far above "
            "reorder_point with no stockout, no active promo, and no supplier issue nearby is an "
            "over-ordering / inventory_spike pattern, not a healthy surplus. Check "
            "get_replenishment_history for a run of oversized orders that were fully received (units_received "
            "== units_ordered) — a fulfillment gap would look different (partial receipt), so a clean, "
            "fully-received order history alongside flat sales is what distinguishes 'ordered too much' "
            "from 'a shipment problem'."
        ),
        "tags": "inventory,stockout,inventory_spike,replenishment,over_ordering",
        "source_doc": "SOP_Inventory_Anomaly_v2.pdf",
    },
    {
        "id": "sop_007",
        "text": (
            "SOP: Confidence Scoring, Escalation, and Honest 'Unknown' Outcomes\n"
            "confidence_score >= 0.7 completes the investigation; below 0.7 auto-escalates to a human "
            "analyst with the full evidence trail attached. "
            "A meaningful fraction of real anomalies genuinely have no discoverable cause in the available "
            "data: inventory healthy, no supplier degradation, no promo nearby, no return or complaint "
            "spike, and yet the decline itself is real and queryable. In that situation, the correct, "
            "highest-quality answer is anomaly_category='unknown' with a low confidence_score and a "
            "root_cause that says plainly that no cause was found in inventory, supplier, promotion, "
            "returns, or complaint data — this is not a worse outcome than forcing a plausible-sounding "
            "explanation onto thin evidence, it is the more trustworthy one. Do not treat 'I found "
            "nothing' as license to reach for the nearest tool result that could arguably be related; only "
            "cite a cause that a tool result actually supports for this investigation's own entities."
        ),
        "tags": "confidence,escalation,unknown,honesty,human_review",
        "source_doc": "SOP_Agent_Escalation_v2.pdf",
    },
    {
        "id": "sop_008",
        "text": (
            "SOP: Using Knowledge Search Results Correctly\n"
            "A knowledge_search hit (SOP or Past Case) tells you what pattern to check for and which tool "
            "is likely to confirm or rule it out — it is never itself evidence for the investigation you "
            "are currently running, and its wording should not be copied into root_cause as if it were. "
            "Concretely: if a Past Case describes 'a carrier outage caused a shipping-complaint spike at "
            "one store', your job is to call get_customer_complaints against THIS investigation's own "
            "store/sku and confirm the same pattern shows up in its data — not to restate the Past Case's "
            "narrative because the symptoms sound similar. Past Cases intentionally describe patterns "
            "and reasoning rather than naming a specific store, SKU, or supplier id, precisely so they "
            "cannot be mistaken for this investigation's own entities — any store/SKU/supplier/promo id "
            "in your final root_cause must come from a tool result you called in this conversation, never "
            "from a knowledge_search excerpt."
        ),
        "tags": "knowledge_search,grounding,evidence,methodology",
        "source_doc": "SOP_Knowledge_Search_Usage_v1.pdf",
    },
]

# ── Past Cases ────────────────────────────────────────────────────────────────

PAST_CASES = [
    {
        "id": "case_001",
        "text": (
            "Past Case: Over-Ordering Mistaken for a Supplier or Demand Problem\n"
            "A SKU/store pair showed stock_on_hand sitting more than 10x reorder_point, which initially "
            "looked concerning enough to investigate as a possible fulfillment error. "
            "get_replenishment_history showed a run of oversized orders (250-320 units each, well above "
            "the SKU's normal order size) spaced roughly every 10 days, every one of them fully received "
            "(units_received == units_ordered every time). Sales for the same sku/store stayed flat and "
            "unremarkable across the same window — no promo, no supplier degradation, no stockout anywhere "
            "nearby. "
            "Root cause: this was over-ordering, not a supply chain or demand issue — someone kept placing "
            "replenishment orders sized for a sell-through rate the SKU never had. "
            "Resolution: replenishment cadence corrected to match actual sell-through, no supplier or "
            "quality action needed. "
            "Lesson: a fully-received oversized-order history plus flat sales is the signature of "
            "inventory_spike, distinct from a stockout (which shows the opposite direction against "
            "reorder_point) and distinct from a supplier problem (which would show delayed or partial "
            "receipt, not full receipt of too much stock)."
        ),
        "tags": "inventory_spike,over_ordering,replenishment,reorder_point",
        "source_doc": "CaseReport_Inventory_001.pdf",
    },
    {
        "id": "case_002",
        "text": (
            "Past Case: A Steep Discount That Barely Moved Units\n"
            "A promotion with a substantial discount (in the 20-50% range) closed with "
            "underperformance_flag=true from get_promotion_performance: actual_uplift_pct came in at a "
            "small single-digit percentage against a projected_uplift_pct several times larger. "
            "margin_impact was negative — the promo cost real margin without buying meaningful extra "
            "volume. "
            "Before concluding 'this SKU doesn't respond to promotions', a second get_promotion_performance "
            "call against a different, organic promo_id for the same SKU showed a healthy uplift at a "
            "comparable discount tier, ruling that alternative explanation out. No inventory or supplier "
            "issue was present anywhere near this SKU/store during the promo window. "
            "Resolution: promo discontinued, discount depth reviewed against this SKU's actual price "
            "elasticity. "
            "Lesson: underperformance_flag plus a same-SKU historical contrast (via a second promo_id "
            "lookup, or get_underperforming_promotions if the promo_id wasn't known up front) are two "
            "independent, corroborating pieces of evidence — don't stop at the flag alone if a same-SKU "
            "comparison is available."
        ),
        "tags": "promotion_underperform,underperformance_flag,margin_impact,discount",
        "source_doc": "CaseReport_Promotion_002.pdf",
    },
    {
        "id": "case_003",
        "text": (
            "Past Case: A Real Sales Decline With No Discoverable Cause\n"
            "A SKU/store showed a genuine, sustained drop in sale frequency over roughly six weeks — not a "
            "data artifact, the decline was clearly visible in get_sales_data / get_stores_with_sku_decline. "
            "get_inventory_levels showed healthy stock well above reorder_point throughout, ruling out a "
            "stockout. No supplier serving this SKU had degradation_flag or an elevated defect_rate. No "
            "promotion had recently run or ended nearby. get_return_reasons and get_customer_complaints "
            "showed nothing above baseline for this SKU or store. "
            "Root cause: none of the tool-observable domains (inventory, supplier, promotion, returns, "
            "complaints) explained the decline — most likely a demand-side shift outside this system's "
            "data (competitor activity, seasonality, changing customer preference), but that could not be "
            "confirmed with available tools. "
            "Resolution: anomaly_category set to 'unknown', confidence_score set low, investigation "
            "escalated for human review rather than assigning a cause the data didn't support. "
            "Lesson: this was the correct outcome, not an incomplete investigation. When every relevant "
            "tool has been checked and none shows an anomaly, say so plainly rather than picking the "
            "least-implausible tool result and presenting it as the cause."
        ),
        "tags": "sales_drop,unknown,honesty,unexplained,confidence",
        "source_doc": "CaseReport_SalesDrop_003.pdf",
    },
    {
        "id": "case_004",
        "text": (
            "Past Case: A Catalog Edit That Preceded a Sizing-Return Spike\n"
            "get_return_reasons for a SKU showed a sizing-related reason_code as dominant, well above "
            "low_sample_warning territory, concentrated in the two weeks before the investigation. "
            "get_product_listing_changes on that same SKU showed a size_chart/size_guide field_changed "
            "entry roughly two weeks earlier — the change_date landed just before the return spike began, "
            "and no other field (price, images, description) had changed nearby. Sales volume and "
            "inventory for the SKU stayed normal throughout; the return rate itself was the only anomaly. "
            "Resolution: size chart reverted / corrected, sizing-return rate normalized within about ten "
            "days. "
            "Lesson: a size_chart or size_guide edit that predates a sizing-reason return spike on the "
            "same SKU is a directly-confirming pair (both facts come from tool calls against the same "
            "sku_id) — stronger evidence than either fact alone, and worth citing together in root_cause "
            "rather than just the return spike in isolation."
        ),
        "tags": "return_surge,listing_change,size_chart,sizing",
        "source_doc": "CaseReport_Returns_004.pdf",
    },
    {
        "id": "case_005",
        "text": (
            "Past Case: A Store-Level Shipping Complaint Spike With No Product Signal\n"
            "get_customer_complaints grouped by category for one store showed 'shipping' as overwhelmingly "
            "dominant — a large majority of that store's complaint volume over about ten days, describing "
            "late arrivals and stuck tracking. Re-running the same query scoped to category='shipping' and "
            "store_id for that store confirmed the concentration wasn't an artifact of aggregation. Every "
            "SKU sold through that store showed normal return rates and no defect-related complaints, and "
            "no supplier serving that store's inventory showed degradation_flag or elevated defect_rate — "
            "there was no product-quality signal anywhere. "
            "Root cause: a store/route-level delivery or carrier issue specific to that store's fulfillment "
            "path, not a product problem. "
            "Resolution: orders rerouted through a different fulfillment path for that store while the "
            "carrier issue was resolved; complaint volume returned to baseline within about a week. "
            "Lesson: when a complaint spike is store-scoped and category-dominant with no matching "
            "return/defect signal on any specific SKU, the store's fulfillment path is the more likely "
            "cause than the product — but confirm the category concentration with a store-scoped tool "
            "call on this investigation's own store, don't just recognize the pattern and stop there."
        ),
        "tags": "customer_complaint,shipping,store_scoped,carrier",
        "source_doc": "CaseReport_Complaints_005.pdf",
    },
    {
        "id": "case_006",
        "text": (
            "Past Case: Multiple Independent Root Causes Behind One Broad Anomaly Report\n"
            "A single anomaly report described several symptoms together: declining sales, an uptick in "
            "returns, and rising complaints, all loosely attributed to 'something wrong' with one part of "
            "the business. Investigating each domain independently (rather than assuming one shared cause) "
            "surfaced three separate, unrelated findings: a listing/size-guide edit driving sizing returns "
            "on one SKU, a promotion ending and pulling forward demand on a different SKU, and a supplier "
            "defect_rate spike driving quality complaints on a third. None of the three connected to each "
            "other in any tool result. "
            "Resolution: each cause addressed independently — listing corrected, promo cadence reviewed, "
            "supplier placed on a quality hold. "
            "Lesson: when an anomaly report bundles multiple symptoms, don't stop investigating once one "
            "plausible cause is confirmed for one symptom — check whether the other symptoms have their own, "
            "independent evidence rather than assuming they all trace back to the same root cause."
        ),
        "tags": "multi_signal,independent_causes,sales_drop,returns,complaints",
        "source_doc": "CaseReport_MultiSignal_006.pdf",
    },
]

def random_past_date():
    start = date(2025, 1, 1)
    delta = (date(2026, 6, 30) - start).days
    import random as r
    return (start + timedelta(days=r.randint(0, delta))).isoformat()

def main():
    # Same knowledge_base.service.get_collection() the live app uses, so
    # seeding writes to the exact table/embedding-function knowledge_search
    # and the CRUD router read from — no separate seed-only code path.
    col = get_collection()

    # Wipe every existing row first (old seed content referenced fabricated
    # entity ids that don't exist in the live Postgres data and don't match
    # the current ID formats agent/grounding.py expects — re-running this
    # script is meant to fully replace the knowledge base, not add to it).
    existing = col.get()
    if existing["ids"]:
        col.delete(ids=existing["ids"])
        print(f"Deleted {len(existing['ids'])} existing chunk rows before reseeding.")

    all_docs = SOPS + PAST_CASES

    ids, texts, metadatas = [], [], []
    for d in all_docs:
        category = "SOP" if d["id"].startswith("sop") else "Past Case"
        chunks = chunk_text(d["text"])
        chunk_ids = [d["id"]] if len(chunks) == 1 else [f"{d['id']}__{i}" for i in range(len(chunks))]
        created_at = random_past_date()
        for i, (chunk_id, chunk) in enumerate(zip(chunk_ids, chunks)):
            ids.append(chunk_id)
            texts.append(chunk)
            metadatas.append({
                "category": category,
                "tags": d["tags"],
                "source_doc": d["source_doc"],
                "created_at": created_at,
                "parent_document_id": d["id"],
                "chunk_index": i,
                "total_chunks": len(chunks),
                "full_text": d["text"],
            })

    # No manual embeddings — col's embedding_function generates them so every
    # row is embedded the exact same way knowledge_search will embed queries.
    col.upsert(ids=ids, documents=texts, metadatas=metadatas)

    print(f"retail_kb seeded -> {col.count()} chunk rows ({len(all_docs)} documents: {len(SOPS)} SOPs + {len(PAST_CASES)} Past Cases)")

if __name__ == "__main__":
    main()