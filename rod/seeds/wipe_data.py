"""
seeds/wipe_data.py
"""
from db import get_conn

def wipe_all_data():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                TRUNCATE 
                    rod_auth."user",
                    reference.products,
                    reference.sku,
                    reference.suppliers,
                    reference.stores,
                    sales.sales,
                    sales.sale_items,
                    inventory.inventory,
                    inventory.replenishment_history,
                    promotions.promotions,
                    promotions.promotion_performance,
                    returns.return_reasons,
                    customers.customer_complaints,
                    suppliers.supplier_delivery,
                    orchestration.catalog_changes
                CASCADE;
            """)
        conn.commit()
        print("Success: All data wiped. Tables structures are intact and ready for re-seeding.")
    except Exception as e:
        conn.rollback()
        print(f"Error wiping data: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    wipe_all_data()