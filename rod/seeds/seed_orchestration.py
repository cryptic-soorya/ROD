"""
seeds/seed_orchestration.py
Run AFTER seed_reference.py (catalog_changes needs reference.sku).

Seeds ONLY the reference-style parts of orchestration:
    agents            -- the fixed set of agent definitions your system uses
    catalog_changes   -- listing edit history (renamed from
                          product_listing_changes; keyed by sku_id now)

Deliberately NOT seeding: investigations, hypotheses, root_causes,
agent_executions, user_queries, reports, audit_logs, tool_calls.
Those are runtime records your actual agent creates while investigating
real anomalies -- bulk-faking them would just be fake investigation
history with no connection to real tool calls or real findings. Your
seed_anomaly.py-style approach (inject one deliberate, coherent scenario
into the underlying data, then let the real agent investigate it and
generate its own investigation/hypothesis/report rows) is the right
model for that data, not a bulk generator like this file.
"""

import random
from datetime import date, timedelta
from db import get_conn, bulk_insert, fetch_ids

random.seed(49)

N_CATALOG_CHANGES = 800

AGENTS = [
    ("agent_orchestrator", "Orchestrator", "coordination",
     "Routes investigations to the right specialist agent and assembles the final report.",
     "planning,delegation,report_assembly"),
    ("agent_sales", "Sales Analyst", "specialist",
     "Investigates revenue and units_sold anomalies via sales tools.",
     "get_sales_data,get_stores_with_sales_decline"),
    ("agent_inventory", "Inventory Analyst", "specialist",
     "Investigates stockouts and replenishment gaps.",
     "get_inventory_levels,get_replenishment_history"),
    ("agent_supplier", "Supplier Analyst", "specialist",
     "Investigates delivery degradation and defect rates.",
     "get_delivery_performance"),
    ("agent_promo", "Promotion Analyst", "specialist",
     "Investigates promo underperformance and post-promo effects.",
     "get_promotion_performance"),
    ("agent_returns", "Returns Analyst", "specialist",
     "Investigates return rate spikes and dominant reasons.",
     "get_return_reasons,get_product_listing_changes"),
    ("agent_customer", "Customer Insights Analyst", "specialist",
     "Investigates complaint volume and category spikes.",
     "get_customer_complaints"),
]

CATALOG_FIELDS = ["price", "description", "images", "size_guide", "title"]


def seed_agents(conn):
    bulk_insert(conn, "orchestration.agents",
                ["id", "agent_name", "agent_type", "description", "capabilities", "is_active"],
                [(*a, True) for a in AGENTS])
    print(f"orchestration.agents seeded -> {len(AGENTS)} rows")


def seed_catalog_changes(conn, sku_ids):
    rows = []
    for _ in range(N_CATALOG_CHANGES):
        sku_id = random.choice(sku_ids)
        
        # Dynamic 550-day lookback from today
        change_date = (date.today() - timedelta(days=random.randint(0, 550))).isoformat()
        
        field = random.choice(CATALOG_FIELDS)
        if field == "price":
            old_value, new_value = str(round(random.uniform(10, 100), 2)), str(round(random.uniform(10, 100), 2))
        else:
            old_value, new_value = f"old_{field}_v1", f"new_{field}_v2"
        changed_by = random.choice(["content_team", "auto_sync", "merchandising", "rollback_bot"])
        rows.append((sku_id, change_date, field, old_value, new_value, changed_by))

    bulk_insert(conn, "orchestration.catalog_changes",
                ["sku_id", "change_date", "field_changed", "old_value", "new_value", "changed_by"],
                rows)
    print(f"orchestration.catalog_changes seeded -> {len(rows)} rows")


def main():
    conn = get_conn()
    try:
        sku_ids = fetch_ids(conn, "SELECT sku_id FROM reference.sku")
        if not sku_ids:
            raise RuntimeError("reference.sku is empty -- run seed_reference.py first")

        seed_agents(conn)
        seed_catalog_changes(conn, sku_ids)
        conn.commit()
        print("\norchestration (reference data only) seeding complete.")
        print("investigations/hypotheses/root_causes/reports/etc. are NOT seeded -- "
              "those are populated by the running agent, not fake bulk data.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()