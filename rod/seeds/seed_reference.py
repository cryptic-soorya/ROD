"""
seeds/seed_reference.py

Seeds auth.user + reference.* — the master data every other schema's
seed script FKs into. Run this FIRST, before any of the domain seed
scripts (sales, inventory, promotions, returns, suppliers, customers).

Order matters within this file too:
    auth.user            (no dependencies)
    reference.products   (no dependencies)
    reference.sku        (needs products)
    reference.suppliers  (no dependencies)
    reference.stores     (needs auth.user, for manager_id)

Run: python seeds/seed_reference.py
"""

import hashlib
import random
from db import get_conn, bulk_insert

random.seed(42)  # reproducible runs, matches old common.py convention

N_PRODUCTS = 200
N_STORES = 50
N_SUPPLIERS = 20

SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
COLOURS = ["Black", "White", "Red", "Blue", "Green", "Navy", "Grey", "Beige"]

CATEGORIES = ["Apparel", "Footwear", "Accessories", "Home", "Electronics"]
BRANDS = ["Meridian", "Northline", "Crestway", "Ashfield", "Ravello", "Ironbark"]

_STATES_DISTRICTS = [
    ("California", "Los Angeles"), ("California", "San Diego"),
    ("Texas", "Harris"), ("Texas", "Dallas"),
    ("New York", "Kings"), ("New York", "Queens"),
    ("Illinois", "Cook"), ("Florida", "Miami-Dade"),
    ("Washington", "King"), ("Georgia", "Fulton"),
]

_SUPPLIER_NAMES = [
    "Meridian Textiles", "Crestwood Manufacturing", "Halcyon Supply Co.",
    "Ironvale Goods", "Larkspur Trading", "Northbridge Industries",
    "Wrenfield Partners", "Cobalt & Co.", "Amberline Logistics",
    "Sable Ridge Exports", "Thistledown Mills", "Granite Peak Sourcing",
    "Willowmere Traders", "Fernbrook Supply", "Pinecrest Distribution",
    "Rosemont Manufacturing", "Ashford Global", "Copperfield Goods",
    "Brightwater Exports", "Stonehaven Logistics",
]


def _placeholder_hash(password: str) -> str:
    """
    NOTE: this is NOT how your real auth system hashes passwords —
    that logic lives in auth_middleware.py / wherever /auth/login
    verifies credentials, which hasn't been shared yet. This sha256
    placeholder lets the DB accept a NOT NULL pass_hash and lets you
    log in via direct queries for testing, but it will NOT match
    whatever bcrypt/argon2/etc. your real login endpoint expects.
    Swap this out before relying on seeded users to log in for real.
    """
    return hashlib.sha256(password.encode()).hexdigest()


def seed_users(conn):
    """1 admin (AD001) + 1 manager per store (SM001..SM050)."""
    rows = [("AD001", "System Admin", "admin", "admin",
              _placeholder_hash("admin123"), "555-0100",
              "admin@rod.local", None)]

    manager_first = ["Alex", "Jordan", "Sam", "Taylor", "Morgan", "Casey","Ron","Esha","Mary",
                      "Riley", "Jamie", "Drew", "Avery","Joseph","George","Ken","Eben","Soorya","Namina","Mishal"]
    manager_last = ["Reed", "Bennett", "Coleman", "Hayes", "Foster","Philip","Joe","Sameer","Sijin","Santhosh","Howard","Booth"
                     "Marsh", "Pratt", "Lowe", "Vance", "Doyle"]

    for i in range(1, N_STORES + 1):
        eid = f"SM{i:03d}"
        name = f"{random.choice(manager_first)} {random.choice(manager_last)}"
        rows.append((
            eid, name, "manager", f"mgr{i:03d}",
            _placeholder_hash(f"manager{i}"),
            f"555-{1000 + i}",
            f"mgr{i:03d}@rod.local", None,
        ))

    bulk_insert(conn, "rod_auth.\"user\"",
                ["eid", "name", "role", "username", "pass_hash",
                 "phone_no", "email", "address"],
                rows)
    print(f"auth.user seeded -> {len(rows)} rows (1 admin + {N_STORES} managers)")


def seed_products(conn):
    rows = []
    for i in range(1, N_PRODUCTS + 1):
        pid = f"P{i:04d}"
        rows.append((
            pid,
            f"{random.choice(BRANDS)} {random.choice(CATEGORIES)} Item {i}",
            random.choice(CATEGORIES),
            random.choice(BRANDS),
            f"Standard {random.choice(CATEGORIES).lower()} product.",
            "active",
        ))
    bulk_insert(conn, "reference.products",
            ["product_id", "product_name", "category", "brand", "description", "status"],
            rows)
    print(f"reference.products seeded -> {len(rows)} rows")
    return [r[0] for r in rows]


def seed_sku(conn, product_ids):
    """Every product gets 2-5 variants, same generation logic as old common.py."""
    rows = []
    for pid in product_ids:
        n_variants = random.randint(2, 5)
        combos = random.sample([(s, c) for s in SIZES for c in COLOURS], n_variants)
        for idx, (size, colour) in enumerate(combos, start=1):
            sku_id = f"{pid}-SKU{idx:02d}"
            mrp = random.randint(500, 20000)  # cents, or your smallest currency unit
            rows.append((sku_id, pid, size, colour, mrp))
    bulk_insert(conn, "reference.sku",
                ["sku_id", "product_id", "size", "colour", "mrp"],
                rows)
    print(f"reference.sku seeded -> {len(rows)} rows")
    return [r[0] for r in rows]


def seed_suppliers(conn):
    rows = []
    for i in range(1, N_SUPPLIERS + 1):
        supplier_id = f"SUP{i:02d}"
        name = _SUPPLIER_NAMES[i - 1] if i - 1 < len(_SUPPLIER_NAMES) else f"Supplier {i}"
        slug = name.lower().replace(" ", "").replace(".", "").replace("&", "and")
        rows.append((supplier_id, name, f"contact@{slug}.com", f"555-{2000 + i}"))
    bulk_insert(conn, "reference.suppliers",
                ["supplier_id", "name", "email", "phone"],
                rows)
    print(f"reference.suppliers seeded -> {len(rows)} rows")
    return [r[0] for r in rows]


def seed_stores(conn):
    """One manager per store: SM001 -> S001, SM002 -> S002, etc."""
    rows = []
    for i in range(1, N_STORES + 1):
        store_id = f"S{i:03d}"
        manager_id = f"SM{i:03d}"
        state, district = random.choice(_STATES_DISTRICTS)
        rows.append((store_id, district, state, "USA", manager_id, True))
    bulk_insert(conn, "reference.stores",
                ["store_id", "district", "state", "country", "manager_id", "is_active"],
                rows)
    print(f"reference.stores seeded -> {len(rows)} rows")


def main():
    conn = get_conn()
    try:
        seed_users(conn)          # must run before stores (manager_id FK)
        product_ids = seed_products(conn)
        seed_sku(conn, product_ids)
        seed_suppliers(conn)
        seed_stores(conn)         # needs auth.user, so runs last
        conn.commit()
        print("\nreference + auth seeding complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()