"""
seeds/seed_anomaly_variants.py

Companion to seed_anomaly.py. That script injects ONE coherent multi-stage
story (supplier_delay -> stockout -> sales_drop -> return_surge ->
customer_complaint) all tangled into a single sku/store/supplier -- great
for testing whether the agent can trace a causal chain, but it never
produces a clean, single-cause example of inventory_spike or
promotion_underperform, and it never gives the agent a sales_drop with NO
supporting cause anywhere (i.e. a case where an honest low confidence_score
and anomaly_category="unknown" is the CORRECT answer, per prompts.py's
"Evidence and honesty" section).

This script injects five independent, single-cause scenarios -- one per
remaining/undertested category from investigations/models.py's
AnomalyCategory enum:

    1. inventory_spike        -- over-ordering, stock balloons, no stockout,
                                  no promo, no supplier issue. Sales stay flat.
    2. promotion_underperform -- a real promo with a real, badly-missed
                                  uplift target. No inventory/supplier issue.
    3. sales_drop (unexplained) -- genuine demand softness. Inventory fine,
                                  supplier fine, no complaint/return spike.
                                  Tests that the agent says "unknown" /
                                  low confidence rather than forcing a cause.
    4. return_surge (listing)  -- a catalog/listing change (e.g. size chart)
                                  precedes a spike in sizing-reason returns
                                  for that sku, with sales/inventory/supplier
                                  otherwise normal.
    5. customer_complaint (shipping) -- a shipping-complaint spike at one
                                  store with NO product-quality signal --
                                  deliberately shaped to match case_004 in
                                  the knowledge base (regional carrier
                                  outage), so you can test whether the agent
                                  actually retrieves AND applies that Past
                                  Case rather than just citing it.

Each scenario picks its own sku/store so it does not overlap with
seed_anomaly.py's target (sku_ids[len//3], store_ids[:3]) or with each
other. Run this AFTER seed_anomaly.py (and all the base seed_*.py scripts
it itself depends on).

Run: python seeds/seed_anomaly_variants.py

Schema notes (verified against the live Supabase project's Schema
Visualizer -- reference / sales / returns / inventory / promotions /
orchestration / customers schemas):
    promotions.promotions:            promo_id (PK, text), store_id (text,
                                       nullable), type (text, nullable --
                                       intentionally left unset here),
                                       sku_id (text, nullable), dsct_pct
                                       (int4, nullable), start_date (date,
                                       nullable), end_date (date, nullable)
    promotions.promotion_performance: id (PK/serial int4), promo_id (text,
                                       NOT NULL but with NO unique/exclusion
                                       constraint -- so no ON CONFLICT on
                                       promo_id is possible here), units_sold,
                                       revenue, baseline_units, margin_impact
                                       (all nullable)
    orchestration.catalog_changes:    id (PK int4), sku_id/change_date/
                                       field_changed (NOT NULL), old_value/
                                       new_value/changed_by (nullable)
    customers.customer_complaints:    complaint_id (PK text), complaint_date
                                       (date -- ISO strings are cast fine),
                                       store_id, sku_id, sale_id, category,
                                       description
"""

import random
from datetime import date, timedelta
from psycopg2.extras import execute_values
from db import get_conn, bulk_insert, fetch_ids

random.seed(212)

TODAY = date.today()


def _pick(sku_ids, store_ids, sku_divisor, store_offset):
    """Same style as seed_anomaly.py's pick_targets, but parameterized so
    each scenario below gets a different sku/store than the others and
    than seed_anomaly.py's own target (sku_ids[len//3], store_ids[:3])."""
    sku_id = sku_ids[len(sku_ids) // sku_divisor]
    store_id = store_ids[store_offset % len(store_ids)]
    return sku_id, store_id


# ── 1. inventory_spike ───────────────────────────────────────────────────────
# Over-ordering relative to actual sell-through: stock_on_hand balloons well
# above reorder_point (the opposite problem from a stockout), sales stay
# flat/normal the whole time, and there's no promo or supplier degradation
# anywhere near this sku/store -- so the ONLY anomalous signal is inventory
# itself, which is what should drive anomaly_category="inventory_spike"
# rather than the agent reaching for a supplier/promo explanation it can't
# actually find evidence for.

def seed_inventory_spike(conn, sku_id, store_id, supplier_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE inventory.inventory
            SET stock_on_hand = %s, reorder_point = %s, last_audited = %s
            WHERE sku_id = %s AND store_id = %s
            """,
            (850, 40, TODAY.isoformat(), sku_id, store_id),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO inventory.inventory
                    (sku_id, store_id, stock_on_hand, reorder_point, last_audited)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (sku_id, store_id, 850, 40, TODAY.isoformat()),
            )

    # A run of oversized replenishment orders, all fully received (no
    # supply-side gap -- the problem is demand-side over-ordering, not a
    # fulfillment failure), landing well before today so the excess stock
    # has clearly been sitting unsold rather than just arriving.
    rows = []
    for i in range(4):
        order_day = TODAY - timedelta(days=50 - i * 10)
        received_day = order_day + timedelta(days=4)  # normal lead time
        units_ordered = random.randint(250, 320)
        rows.append((sku_id, store_id, order_day.isoformat(), received_day.isoformat(),
                     units_ordered, units_ordered, supplier_id))  # fully received

    bulk_insert(conn, "inventory.replenishment_history",
                ["sku_id", "store_id", "order_date", "received_date",
                 "units_ordered", "units_received", "supplier_id"],
                rows)
    print(f"[inventory_spike] sku={sku_id} store={store_id}: "
          f"stock_on_hand=850 (reorder_point=40), {len(rows)} oversized-but-fully-received orders")


# ── 2. promotion_underperform ────────────────────────────────────────────────
# A promo with a meaningful discount ran and ended recently; actual uplift
# came in far below what get_promotion_performance's projected_uplift_pct
# formula (discount_pct * 2) would predict. No inventory or supplier issue
# anywhere near this sku/store -- the promo itself is the whole story.

def seed_promotion_underperform(conn, sku_id, store_id):
    # Numeric-only after the prefix, matching agent/grounding.py's own
    # ENTITY_PATTERNS regex (\bPROMO-?\d{4,6}\b) -- an alphanumeric id like
    # "PROMO-VAR001" would never be recognized as an entity at all, silently
    # defeating grounding checks against this scenario.
    promo_id = f"PROMO{random.randint(90000, 99999)}"
    start_date = TODAY - timedelta(days=20)
    end_date = TODAY - timedelta(days=6)
    discount_pct = 25  # dsct_pct is int4 in the real schema, not a float
    baseline_units = 400
    units_sold = 420  # actual_uplift_pct ~5.0, vs projected 50.0 (dsct_pct * 2)

    with conn.cursor() as cur:
        # `type` is nullable in the real schema, so it's fine to leave unset
        # here -- this promo doesn't need a category to make its point.
        cur.execute(
            """
            INSERT INTO promotions.promotions
                (promo_id, sku_id, store_id, start_date, end_date, dsct_pct)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (promo_id) DO NOTHING
            """,
            (promo_id, sku_id, store_id, start_date.isoformat(), end_date.isoformat(), discount_pct),
        )
        # No ON CONFLICT here: promotion_performance's own PK is the serial
        # `id` column -- there is no unique constraint on promo_id for
        # Postgres to match against, so ON CONFLICT (promo_id) would raise
        # "there is no unique or exclusion constraint" at runtime.
        cur.execute(
            """
            INSERT INTO promotions.promotion_performance
                (promo_id, units_sold, baseline_units, revenue, margin_impact)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (promo_id, units_sold, baseline_units, round(units_sold * 45.0, 2), round(-units_sold * 45.0 * discount_pct / 100, 2)),
        )
    print(f"[promotion_underperform] promo={promo_id} sku={sku_id} store={store_id}: "
          f"discount={discount_pct}% (projected uplift 50.0%), actual uplift ~5.0%")


# ── 3. sales_drop, unexplained ───────────────────────────────────────────────
# A real, queryable revenue decline with NOTHING else anomalous nearby:
# inventory stays well-stocked (no stockout), no supplier degradation, no
# return or complaint spike. This is the case your prompts.py explicitly
# asks the agent to handle honestly -- "if you cannot determine a root
# cause, say so plainly... set confidence_score low rather than forcing a
# false explanation." Use this to test that the agent doesn't invent a
# supplier/inventory story just because those tools are available to call.

def seed_unexplained_sales_drop(conn, sku_id, store_id, all_sku_ids):
    pre_start = TODAY - timedelta(days=90)
    window_start = TODAY - timedelta(days=45)

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM sales.sale_items
            WHERE sale_id IN (
                SELECT sale_id FROM sales.sales
                WHERE sku_id = %s AND store_id = %s AND sale_date >= %s
            )
            """,
            (sku_id, store_id, pre_start.isoformat()),
        )
        cur.execute(
            "DELETE FROM sales.sales WHERE sku_id = %s AND store_id = %s AND sale_date >= %s",
            (sku_id, store_id, pre_start.isoformat()),
        )

        # Ensure inventory looks healthy throughout -- rules out a stockout
        # explanation so the decline is genuinely unexplained by the data.
        cur.execute(
            """
            UPDATE inventory.inventory
            SET stock_on_hand = %s, reorder_point = %s, last_audited = %s
            WHERE sku_id = %s AND store_id = %s
            """,
            (120, 30, TODAY.isoformat(), sku_id, store_id),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO inventory.inventory
                    (sku_id, store_id, stock_on_hand, reorder_point, last_audited)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (sku_id, store_id, 120, 30, TODAY.isoformat()),
            )

    sales_data = []
    for d in range(45):
        day = pre_start + timedelta(days=d)
        if random.random() < 0.55:  # normal baseline frequency
            sales_data.append((sku_id, store_id, day.isoformat(), round(random.uniform(15.0, 500.0), 2)))
    for d in range(45):
        day = window_start + timedelta(days=d)
        if random.random() < 0.20:  # quiet decline, no external cause injected
            sales_data.append((sku_id, store_id, day.isoformat(), round(random.uniform(15.0, 500.0), 2)))

    with conn.cursor() as cur:
        generated = execute_values(
            cur,
            "INSERT INTO sales.sales (sku_id, store_id, sale_date, total_price) VALUES %s RETURNING sale_id",
            sales_data,
            fetch=True,
        )
        sale_items_data = []
        for (sale_id,) in generated:
            for _ in range(random.randint(1, 3)):
                item_sku_id = random.choice(all_sku_ids)
                sale_items_data.append((sale_id, item_sku_id, random.randint(1, 4),
                                        round(random.uniform(5.0, 150.0), 2), 0.0))
        execute_values(
            cur,
            "INSERT INTO sales.sale_items (sale_id, sku_id, quantity, mrp, dscnt_applied) VALUES %s",
            sale_items_data,
        )

    print(f"[sales_drop/unexplained] sku={sku_id} store={store_id}: "
          f"{len(sales_data)} sales rewritten, no inventory/supplier/return/complaint anomaly injected")


# ── 4. return_surge, listing-driven ──────────────────────────────────────────
# A catalog change (e.g. a size chart edit) precedes a spike in sizing-reason
# returns for the same sku. Sales volume and inventory stay normal -- the
# return rate itself is the anomaly, and the catalog_changes row is the
# only causal thread get_product_listing_changes can surface.

def seed_listing_return_surge(conn, sku_id, store_id):
    change_date = TODAY - timedelta(days=18)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO orchestration.catalog_changes
                (sku_id, field_changed, old_value, new_value, change_date, changed_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (sku_id, "size_chart", "US sizing (standard fit)", "US sizing (slim fit, updated 2026-07)",
             change_date.isoformat(), "catalog-team"),
        )

        # A handful of baseline sales to attach the return spike to.
        sales_data = []
        for d in range(30):
            day = change_date - timedelta(days=15) + timedelta(days=d)
            if random.random() < 0.5:
                sales_data.append((sku_id, store_id, day.isoformat(), round(random.uniform(20.0, 300.0), 2)))
        generated = execute_values(
            cur,
            "INSERT INTO sales.sales (sku_id, store_id, sale_date, total_price) VALUES %s RETURNING sale_id, sale_date",
            sales_data,
            fetch=True,
        )

    rows = []
    for sale_id, sale_date_val in generated:
        sale_date_str = sale_date_val if isinstance(sale_date_val, str) else sale_date_val.isoformat()
        sale_dt = date.fromisoformat(sale_date_str)
        if sale_dt < change_date:
            continue  # only sales after the listing change are at risk of a sizing return
        if random.random() < 0.55:  # elevated sizing-return rate post-change
            return_date = min(TODAY, sale_dt + timedelta(days=random.randint(2, 12))).isoformat()
            rows.append((sku_id, store_id, sale_id, return_date, "sizing",
                        "Customer reports item runs differently than expected -- size chart mismatch",
                        random.randint(1, 4)))

    bulk_insert(conn, "returns.return_reasons",
                ["sku_id", "store_id", "sale_id", "return_date", "reason_code",
                 "reason_text", "units_returned"],
                rows)
    print(f"[return_surge/listing] sku={sku_id} store={store_id}: "
          f"catalog change on {change_date.isoformat()}, {len(rows)} sizing returns after it")


# ── 5. customer_complaint, shipping-driven ──────────────────────────────────
# A spike of shipping-category complaints at one store, no product-quality
# signal anywhere, deliberately shaped to match case_004 in the seeded
# knowledge base (regional carrier outage -> shipping complaint doubling).
# Use this to test whether the agent actually retrieves AND applies that
# Past Case, per your prompts.py note that knowledge_search results "tell
# you what to check next" but must be independently confirmed, not just
# restated.

def seed_shipping_complaint_spike(conn, store_id):
    rows = []
    for i in range(1, 91):
        complaint_id = f"CMP-VAR{i:04d}"
        complaint_date = (TODAY - timedelta(days=random.randint(0, 10))).isoformat()
        rows.append((complaint_id, complaint_date, store_id, None, None,
                    "shipping", "Order arrived days late / delivery tracking stuck -- multiple reports this week"))

    bulk_insert(conn, "customers.customer_complaints",
                ["complaint_id", "complaint_date", "store_id", "sku_id",
                 "sale_id", "category", "description"],
                rows)
    print(f"[customer_complaint/shipping] store={store_id}: {len(rows)} shipping complaints, no quality signal")


def main():
    conn = get_conn()
    try:
        sku_ids = fetch_ids(conn, "SELECT sku_id FROM reference.sku ORDER BY sku_id")
        store_ids = fetch_ids(conn, "SELECT store_id FROM reference.stores ORDER BY store_id")
        supplier_ids = fetch_ids(conn, "SELECT supplier_id FROM reference.suppliers ORDER BY supplier_id")
        all_sku_ids = sku_ids

        if not sku_ids or not store_ids or not supplier_ids:
            raise RuntimeError("reference tables are empty -- run seed_reference.py first")

        print(f"\n{'='*60}\nInjecting 5 additional single-cause anomaly scenarios\n{'='*60}\n")

        sku, store = _pick(sku_ids, store_ids, sku_divisor=7, store_offset=3)
        seed_inventory_spike(conn, sku, store, supplier_ids[0])

        sku, store = _pick(sku_ids, store_ids, sku_divisor=2, store_offset=4)
        seed_promotion_underperform(conn, sku, store)

        sku, store = _pick(sku_ids, store_ids, sku_divisor=5, store_offset=5)
        seed_unexplained_sales_drop(conn, sku, store, all_sku_ids)

        sku, store = _pick(sku_ids, store_ids, sku_divisor=9, store_offset=6)
        seed_listing_return_surge(conn, sku, store)

        _, store = _pick(sku_ids, store_ids, sku_divisor=11, store_offset=7)
        seed_shipping_complaint_spike(conn, store)

        conn.commit()
        print(f"\n{'='*60}\nAll 5 variant scenarios injected & committed.\n{'='*60}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()