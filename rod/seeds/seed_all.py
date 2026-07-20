"""
seeds/seed_all.py

Runs every seed script in the only order that satisfies all the FK
dependencies across schemas:

    1. seed_reference.py     auth.user, reference.* (everything else needs this)
    2. seed_promotions.py    needs reference.sku, reference.stores
    3. seed_sales.py         needs reference.sku, reference.stores
    4. seed_inventory.py     needs reference.*, promotions.promotions (optional FK)
    5. seed_suppliers.py     needs reference.*
    6. seed_returns.py       needs reference.*, sales.sales (optional FK)
    7. seed_customers.py     needs reference.*, sales.sales (optional FK)
    8. seed_orchestration.py needs reference.sku (catalog_changes only)

Run: python seeds/seed_all.py
"""

import subprocess
import sys

SCRIPTS = [
    # "seed_reference.py",
    # "seed_promotions.py",
    # "seed_sales.py",
    # "seed_inventory.py",
    # "seed_suppliers.py",
    "seed_returns.py",
    "seed_customers.py",
    "seed_orchestration.py",
]


def main():
    for script in SCRIPTS:
        print(f"\n{'='*60}\nRunning {script}\n{'='*60}")
        result = subprocess.run([sys.executable, script])
        if result.returncode != 0:
            print(f"\n{script} FAILED -- stopping (later scripts depend on this data).")
            sys.exit(1)

    print(f"\n{'='*60}\nAll 9 schemas seeded successfully.\n{'='*60}")


if __name__ == "__main__":
    main()