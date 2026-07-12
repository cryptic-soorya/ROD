"""
check_referential_integrity.py
Cross-database integrity checker for the sku_id / store_id / supplier_id
migration.

WHY THIS EXISTS:
SQLite cannot enforce a foreign key across separate .db files -- there is
no PRAGMA or workaround that makes it do so. sales.db, customers.db,
promotions.db, returns.db, suppliers.db, and inventory.db all reference
sku_id/store_id values that live in investigations/orchestration.db's
`sku` and `stores` tables, but nothing stops any of those files from
drifting out of sync with the master tables over time.

This script doesn't prevent drift -- it detects it. Run it after any
reseed, and periodically in whatever environment these dbs run in, to
catch dangling references before they cause a confusing "why did this
query return nothing" bug three months from now.

Run: python seeds/check_referential_integrity.py

Exit code: 0 if every retail db is fully consistent with the master
tables, 1 if any dangling references were found (so this can be wired
into a CI check later if useful).
"""
import os
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

ORCH_DB = os.path.join(PROJECT_ROOT, "investigations", "orchestration.db")
RETAIL_DB_DIR = os.path.join(PROJECT_ROOT, "mcp_server", "db")

# table -> (sku column, store column, supplier column) -- None where the
# table doesn't have that kind of reference at all.
RETAIL_DBS = {
    "sales.db": [
        ("sales", "sku_id", "store_id", None),
    ],
    "customers.db": [
        # customer_complaints has no sku_id or store_id -- confirmed real
        # schema is complaint_id/category/complaint_date/description only.
        # Nothing to check here; kept as an empty entry so this file stays
        # a complete map of every retail db, not just the ones with checks.
    ],
    "promotions.db": [
        ("promotion_performance", "sku_id", None, None),
    ],
    "returns.db": [
        ("return_reasons", "sku_id", None, None),
    ],
    "suppliers.db": [
        ("supplier_delivery", "sku_id", None, "supplier_id"),
    ],
    "inventory.db": [
        ("inventory_levels", "sku_id", "store_id", None),
        ("replenishment_history", "sku_id", "store_id", "supplier_id"),
    ],
}


def _check_column(conn, alias, table, column, master_table, master_column):
    """Returns (dangling_count, sample_values) of values in alias.table.column
    that don't exist in the master table on the main connection."""
    query = f"""
        SELECT DISTINCT t.{column}
        FROM {alias}.{table} t
        LEFT JOIN {master_table} m ON t.{column} = m.{master_column}
        WHERE t.{column} IS NOT NULL
          AND m.{master_column} IS NULL
    """
    rows = conn.execute(query).fetchall()
    values = [r[0] for r in rows]
    return len(values), values[:5]


def main():
    if not os.path.exists(ORCH_DB):
        print(f"ERROR: master db not found at {ORCH_DB}")
        print("Run seed_orchestration.py first.")
        sys.exit(1)

    conn = sqlite3.connect(ORCH_DB)
    any_issues = False

    print(f"Master db: {ORCH_DB}")
    print("=" * 70)

    for db_filename, table_specs in RETAIL_DBS.items():
        db_path = os.path.join(RETAIL_DB_DIR, db_filename)
        alias = db_filename.replace(".db", "").replace("-", "_")

        if not os.path.exists(db_path):
            print(f"[SKIP] {db_filename} -- file not found at {db_path}")
            continue

        conn.execute(f"ATTACH DATABASE ? AS {alias}", (db_path,))

        print(f"\n{db_filename}")
        for table, sku_col, store_col, supplier_col in table_specs:
            if sku_col:
                count, sample = _check_column(conn, alias, table, sku_col, "sku", "sku_id")
                status = "OK" if count == 0 else "DANGLING"
                print(f"  {table}.{sku_col:12s} -> sku.sku_id        [{status}]"
                      + (f"  {count} bad values, e.g. {sample}" if count else ""))
                any_issues = any_issues or count > 0

            if store_col:
                count, sample = _check_column(conn, alias, table, store_col, "stores", "id")
                status = "OK" if count == 0 else "DANGLING"
                print(f"  {table}.{store_col:12s} -> stores.id         [{status}]"
                      + (f"  {count} bad values, e.g. {sample}" if count else ""))
                any_issues = any_issues or count > 0

            if supplier_col:
                count, sample = _check_column(conn, alias, table, supplier_col, "suppliers", "id")
                status = "OK" if count == 0 else "DANGLING"
                print(f"  {table}.{supplier_col:12s} -> suppliers.id      [{status}]"
                      + (f"  {count} bad values, e.g. {sample}" if count else ""))
                any_issues = any_issues or count > 0

        conn.execute(f"DETACH DATABASE {alias}")

    print("\n" + "=" * 70)
    if any_issues:
        print("RESULT: dangling references found -- see DANGLING rows above.")
    else:
        print("RESULT: all retail dbs are consistent with sku / stores / suppliers.")

    conn.close()
    sys.exit(1 if any_issues else 0)


if __name__ == "__main__":
    main()
