import random
from datetime import date, timedelta
from psycopg2.extras import execute_values
from db import get_conn

def get_reference_data(cur):
    """Fetch existing IDs from reference schemas to use as foreign keys."""
    cur.execute("SELECT store_id FROM reference.stores")
    store_ids = [row[0] for row in cur.fetchall()]
    
    cur.execute("SELECT sku_id FROM reference.sku")
    sku_ids = [row[0] for row in cur.fetchall()]
    
    return sku_ids, store_ids

def seed_sales(conn, sku_ids, store_ids):
    cur = conn.cursor()
    print("Generating mock sales data...")
    
    # 1. Generate Sales Data
    sales_data = []
    num_sales = 5000  # Adjust the volume as needed
    today = date.today()
    
    for _ in range(num_sales):
        store_id = random.choice(store_ids)
        sku_id = random.choice(sku_ids) # Added sku_id for the sales table
        
        # Schema requires sale_date as text, not a date object
        sale_date = (today - timedelta(days=random.randint(0, 90))).isoformat()
        total_price = round(random.uniform(15.0, 800.0), 2)
        
        # Tuple matches: sku_id, store_id, sale_date, total_price
        sales_data.append((sku_id, store_id, sale_date, total_price))
        
    print(f"Batch inserting {len(sales_data)} sales into sales.sales...")
    
    # 2. Batch Insert Sales and fetch generated sale_ids
    sales_insert_query = """
        INSERT INTO sales.sales (sku_id, store_id, sale_date, total_price)
        VALUES %s
        RETURNING sale_id
    """
    
    generated_sale_records = execute_values(
        cur, 
        sales_insert_query, 
        sales_data, 
        fetch=True
    )
    
    # 3. Generate Line Items based on the returned Sale IDs
    print("Generating mock line items data...")
    sale_items_data = []
    
    for record in generated_sale_records:
        sale_id = record[0]
        num_items = random.randint(1, 6)
        
        for _ in range(num_items):
            item_sku_id = random.choice(sku_ids)
            quantity = random.randint(1, 5)
            
            # Swapped unit_price for mrp and dscnt_applied per schema
            mrp = round(random.uniform(5.0, 150.0), 2)
            dscnt_applied = round(random.uniform(0.0, mrp * 0.2), 2) # Random discount up to 20%
            
            # Tuple matches: sale_id, sku_id, quantity, mrp, dscnt_applied
            sale_items_data.append((sale_id, item_sku_id, quantity, mrp, dscnt_applied))
            
    print(f"Batch inserting {len(sale_items_data)} items into sales.sale_items...")
    
    # 4. Batch Insert Line Items
    items_insert_query = """
        INSERT INTO sales.sale_items (sale_id, sku_id, quantity, mrp, dscnt_applied)
        VALUES %s
    """
    
    execute_values(cur, items_insert_query, sale_items_data)
    cur.close()

def main():
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        sku_ids, store_ids = get_reference_data(cur)
        cur.close()
        
        if not sku_ids or not store_ids:
            print("Error: Missing reference data. Ensure seed_reference.py ran successfully.")
            return
            
        seed_sales(conn, sku_ids, store_ids)
        
        conn.commit()
        print("sales schema successfully seeded!")
        
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Failed: {e}")
        raise e
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()