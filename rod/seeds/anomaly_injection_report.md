# Injected Test Anomalies

Window: 2026-06-16 to 2026-06-30

## P0014 — A_supplier_degrades

**Ground truth:** Supplier SUP05 degraded (avg delivery ~2.5-3.2x baseline of 4.5 days, degradation_flag=1) starting 2026-06-16. Its most recent open order for P0014 never arrived (received_date=NULL). This caused stockouts (stockout_flag=1) in stores ['S012', 'S045', 'S034'], which collapsed units_sold to near zero for the rest of the window.

**Changes made:**

- `suppliers.db:supplier_delivery`: inserted 15 rows for supplier SUP05 / product P0014
- `inventory.db:inventory_levels`: stores ['S012', 'S045', 'S034'] ramp to stock_on_hand=0 by day 4, stockout_flag=1 for remainder of window
- `inventory.db:replenishment_history`: order id=4628 (order_date=2026-06-29) set received_date=NULL — open order stuck with degraded supplier
- `sales.db:sales`: units_sold collapsed to 0-1/day across stores ['S012', 'S045', 'S034'] for the full window (unit price $12.88)

## P0022 — A_supplier_degrades

**Ground truth:** Supplier SUP05 degraded (avg delivery ~2.5-3.2x baseline of 4.5 days, degradation_flag=1) starting 2026-06-16. Its most recent open order for P0022 never arrived (received_date=NULL). This caused stockouts (stockout_flag=1) in stores ['S013', 'S042', 'S011'], which collapsed units_sold to near zero for the rest of the window.

**Changes made:**

- `suppliers.db:supplier_delivery`: inserted 15 rows for supplier SUP05 / product P0022
- `inventory.db:inventory_levels`: stores ['S013', 'S042', 'S011'] ramp to stock_on_hand=0 by day 4, stockout_flag=1 for remainder of window
- `inventory.db:replenishment_history`: order id=1972 (order_date=2026-05-31) set received_date=NULL — open order stuck with degraded supplier
- `sales.db:sales`: units_sold collapsed to 0-1/day across stores ['S013', 'S042', 'S011'] for the full window (unit price $50.39)

## P0096 — B_manufacturer_swap

**Ground truth:** Product P0096 was switched from supplier SUP07 to SUP21 on recent replenishment orders. SUP21 has normal delivery timing (degradation_flag=0) but an elevated defect_rate (0.15-0.25), which shows up as a 'defective' spike in return_reasons and a 'quality' complaint spike in customer_complaints, plus a moderate (not total) sales dip. The trap: a naive check of degradation_flag alone will miss this — the agent needs get_delivery_performance's defect_rate field specifically.

**Changes made:**

- `inventory.db:replenishment_history`: 2 recent orders switched from supplier SUP07 -> SUP21
- `suppliers.db:supplier_delivery`: inserted 15 rows for NEW supplier SUP21: normal delivery timing, defect_rate 0.15-0.25, degradation_flag=0
- `returns.db:return_reasons`: inserted 11 rows with reason_code='defective', sample_size>=20 (avoids low_sample_warning)
- `customers.db:customer_complaints`: inserted 9 'quality' complaints, weighted toward unresolved (backlog signal)
- `sales.db:sales`: units_sold reduced to ~40-65% of original for 0 existing rows in window (moderate dip, not stockout)

## P0086 — B_manufacturer_swap

**Ground truth:** Product P0086 was switched from supplier SUP06 to SUP22 on recent replenishment orders. SUP22 has normal delivery timing (degradation_flag=0) but an elevated defect_rate (0.15-0.25), which shows up as a 'defective' spike in return_reasons and a 'quality' complaint spike in customer_complaints, plus a moderate (not total) sales dip. The trap: a naive check of degradation_flag alone will miss this — the agent needs get_delivery_performance's defect_rate field specifically.

**Changes made:**

- `inventory.db:replenishment_history`: 1 recent orders switched from supplier SUP06 -> SUP22
- `suppliers.db:supplier_delivery`: inserted 15 rows for NEW supplier SUP22: normal delivery timing, defect_rate 0.15-0.25, degradation_flag=0
- `returns.db:return_reasons`: inserted 14 rows with reason_code='defective', sample_size>=20 (avoids low_sample_warning)
- `customers.db:customer_complaints`: inserted 11 'quality' complaints, weighted toward unresolved (backlog signal)
- `sales.db:sales`: units_sold reduced to ~40-65% of original for 0 existing rows in window (moderate dip, not stockout)

