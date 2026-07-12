"""
Shared fake-data constants, reused by every seed_*.py so IDs line up across dbs.

UPDATED for the product_id -> sku_id migration:
    - SKUS / PRODUCT_SKUS / SKU_DETAILS are new. Every product now has 2-5
      SKU variants (size x colour), matching the real sku table shape
      (sku_id, product_id, sku_code, size, colour).
    - All retail-table seed scripts should sample from SKUS (or
      PRODUCT_SKUS[product_id] when they need to stay within one product),
      NOT from PRODUCTS directly, since product_id columns are being renamed
      to sku_id.
    - SUPPLIER_DETAILS is new. Closes the "no suppliers master table" gap
      flagged during the schema review -- supplier_id was previously a
      free-floating code with nothing backing it. This does NOT create a
      cross-db enforced FK (suppliers still isn't referenced by FK from
      suppliers.db's own table, since that lives in a separate file from
      the merged orchestration.db) -- it just gives the new `suppliers`
      reference table in the merged db something real to hold.
"""
import random
from datetime import date, timedelta

random.seed(42)  # reproducible runs

PRODUCTS  = [f"P{str(i).zfill(4)}" for i in range(1, 201)]      # 200 products
STORES    = [f"S{str(i).zfill(3)}" for i in range(1, 51)]       # 50 stores
SUPPLIERS = [f"SUP{str(i).zfill(2)}" for i in range(1, 21)]     # 20 suppliers

START_DATE = date(2025, 1, 1)
END_DATE   = date.today()


def random_date(start=START_DATE, end=END_DATE):
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).isoformat()


def daterange(start=START_DATE, end=END_DATE):
    days = (end - start).days
    for i in range(days + 1):
        yield start + timedelta(days=i)


# ── SKU generation ───────────────────────────────────────────────────────────
# Every product gets 2-5 real variants. This is fake/synthetic like everything
# else in common.py, but it's the first point in the whole codebase where SKU
# actually means something distinct from product -- earlier, "sku" was just
# an alias for product_id with no real size/colour behind it.

SIZES   = ["XS", "S", "M", "L", "XL", "XXL"]
COLOURS = ["Black", "White", "Red", "Blue", "Green", "Navy", "Grey", "Beige"]


def _gen_skus():
    skus = []                 # flat list of every sku_id, for uniform random.choice(SKUS)
    product_skus = {}         # product_id -> [sku_id, ...]
    sku_details = {}          # sku_id -> {product_id, sku_code, size, colour}

    for product_id in PRODUCTS:
        n_variants = random.randint(2, 5)
        combos = random.sample(
            [(s, c) for s in SIZES for c in COLOURS],
            n_variants,
        )
        product_skus[product_id] = []
        for idx, (size, colour) in enumerate(combos, start=1):
            sku_id = f"{product_id}-SKU{idx:02d}"
            # NOTE: previously truncated colour to 3 letters (colour[:3]), which
            # collided for Green/Grey (both -> "GRE") and silently dropped rows
            # via INSERT OR IGNORE downstream. Use the full colour name instead --
            # sku_code is meant to be unique, not maximally compact.
            sku_code = f"{product_id}-{size}-{colour.upper()}"
            skus.append(sku_id)
            product_skus[product_id].append(sku_id)
            sku_details[sku_id] = {
                "product_id": product_id,
                "sku_code": sku_code,
                "size": size,
                "colour": colour,
            }
    return skus, product_skus, sku_details


SKUS, PRODUCT_SKUS, SKU_DETAILS = _gen_skus()


def random_sku():
    """Uniform random sku_id across all products/variants."""
    return random.choice(SKUS)


def random_sku_for_product(product_id):
    """Random sku_id belonging to a specific product, when a script needs to
    stay within one product's variants rather than sampling globally."""
    return random.choice(PRODUCT_SKUS[product_id])


# ── Supplier reference data ──────────────────────────────────────────────────
# Closes the "no suppliers master table" gap. supplier_id values above stay
# the same strings as before, so anything already seeded/joined by
# supplier_id keeps working -- this just adds real names/regions to attach
# to those ids in the new `suppliers` table living in the merged db.

_SUPPLIER_NAME_POOL = [
    "Meridian Textiles", "Crestwood Manufacturing", "Halcyon Supply Co.",
    "Ironvale Goods", "Larkspur Trading", "Northbridge Industries",
    "Wrenfield Partners", "Cobalt & Co.", "Amberline Logistics",
    "Sable Ridge Exports", "Thistledown Mills", "Granite Peak Sourcing",
    "Willowmere Traders", "Fernbrook Supply", "Pinecrest Distribution",
    "Rosemont Manufacturing", "Ashford Global", "Copperfield Goods",
    "Brightwater Exports", "Stonehaven Logistics",
]
_SUPPLIER_REGIONS = ["APAC", "EMEA", "LATAM", "North America"]


def _gen_supplier_details():
    details = {}
    for supplier_id, name in zip(SUPPLIERS, _SUPPLIER_NAME_POOL):
        details[supplier_id] = {
            "name": name,
            "region": random.choice(_SUPPLIER_REGIONS),
        }
    return details


SUPPLIER_DETAILS = _gen_supplier_details()
